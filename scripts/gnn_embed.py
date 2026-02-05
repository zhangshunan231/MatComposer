import json
import argparse
import os
import random
from typing import List, Dict, Any, Tuple

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.nn import Parameter
except ImportError:
    print("Error: PyTorch is required. Please install it with 'pip install torch'.")
    exit(1)

# --- Simple GCN Layer Implementation (No geometric dependency) ---
class GCNLayer(nn.Module):
    def __init__(self, in_features, out_features):
        super(GCNLayer, self).__init__()
        self.weight = Parameter(torch.FloatTensor(in_features, out_features))
        self.bias = Parameter(torch.FloatTensor(out_features))
        self.reset_parameters()

    def reset_parameters(self):
        nn.init.xavier_uniform_(self.weight)
        nn.init.zeros_(self.bias)

    def forward(self, x, adj):
        # x: [N, in_features]
        # adj: [N, N] (Normalized adjacency)
        support = torch.mm(x, self.weight)
        output = torch.mm(adj, support)
        return output + self.bias

# --- Graph Autoencoder Model ---
class GraphEncoder(nn.Module):
    def __init__(self, num_node_types, hidden_dim=64, embed_dim=64):
        super(GraphEncoder, self).__init__()
        # Node type embedding: Map discrete types to continuous vectors
        self.node_embedding = nn.Embedding(num_node_types, hidden_dim)
        
        # GCN Layers
        self.conv1 = GCNLayer(hidden_dim, hidden_dim)
        self.conv2 = GCNLayer(hidden_dim, embed_dim)
        
        self.relu = nn.ReLU()

    def forward(self, x_indices, adj):
        # x_indices: [N] (Node type indices)
        x = self.node_embedding(x_indices) # [N, hidden_dim]
        
        h = self.conv1(x, adj)
        h = self.relu(h)
        z = self.conv2(h, adj) # [N, embed_dim]
        return z

# --- Utilities ---
def load_data(json_path: str) -> Tuple[List[Dict], List[str]]:
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def build_vocab(data: List[Dict]) -> Dict[str, int]:
    node_types = set()
    for graph in data:
        for node in graph.get("nodes", []):
            node_types.add(node["type"])
    
    # Sort for determinism
    sorted_types = sorted(list(node_types))
    return {t: i for i, t in enumerate(sorted_types)}

def process_graph(graph_data: Dict, vocab: Dict[str, int]) -> Tuple[torch.Tensor, torch.Tensor]:
    nodes = graph_data.get("nodes", [])
    links = graph_data.get("links", [])
    num_nodes = len(nodes)
    
    if num_nodes == 0:
        return None, None
        
    # Node Features (Type Indices)
    x_indices = []
    for node in nodes:
        t = node.get("type", "Unknown")
        x_indices.append(vocab.get(t, 0)) # Default to 0 if unknown? 
        # Ideally 0 should be <UNK> if we froze vocab, but here we built vocab from data.
    
    x_tensor = torch.LongTensor(x_indices)
    
    # Adjacency Matrix
    adj = torch.eye(num_nodes) # Self-loops
    for link in links:
        u, v = link["u"], link["v"]
        if u < num_nodes and v < num_nodes:
            adj[u, v] = 1.0
            # Directed or Undirected? Node trees are directed.
            # But for structural clustering, treating as undirected often helps flow.
            # Let's keep directed for now, or symmetric?
            # Symmetric GCN is standard.
            adj[v, u] = 1.0 
            
    # Normalize Adjacency: D^-0.5 A D^-0.5
    row_sum = torch.sum(adj, dim=1)
    d_inv_sqrt = torch.pow(row_sum, -0.5)
    d_inv_sqrt[torch.isinf(d_inv_sqrt)] = 0.
    d_mat_inv_sqrt = torch.diag(d_inv_sqrt)
    
    norm_adj = torch.mm(torch.mm(d_mat_inv_sqrt, adj), d_mat_inv_sqrt)
    
    return x_tensor, norm_adj

def get_graph_embedding(model, x, adj):
    # Get node embeddings
    z_nodes = model(x, adj) # [N, embed_dim]
    
    # Global Pooling: Mean of node embeddings
    # Simple readout function
    graph_embed = torch.mean(z_nodes, dim=0)
    return graph_embed

def train_model(data, vocab, epochs=50, hidden_dim=64, embed_dim=64, lr=0.01):
    num_types = len(vocab)
    model = GraphEncoder(num_types, hidden_dim, embed_dim)
    optimizer = optim.Adam(model.parameters(), lr=lr)
    
    print(f"Training GNN on {len(data)} graphs for {epochs} epochs...")
    
    model.train()
    for epoch in range(epochs):
        total_loss = 0
        count = 0
        
        # Shuffle data
        random.shuffle(data)
        
        for graph in data:
            x, adj = process_graph(graph, vocab)
            if x is None: continue
            
            optimizer.zero_grad()
            
            # Forward
            z = model(x, adj)
            
            # Reconstruction Loss (Dot product should reconstruct Adjacency)
            # Pred = Sigmoid(Z Z^T)
            # We only sample some edges to compute loss for efficiency if graphs are huge,
            # but node trees are small (<100 nodes), so full matrix is fine.
            
            z_zt = torch.mm(z, z.t())
            
            # Target is the raw adjacency (binary)
            # We need to reconstruct the adjacency used for input (which has self-loops)? 
            # Or the original link structure?
            # Let's use the normalized adj as target proxy or just raw connectivity.
            # Let's use raw connectivity from `process_graph` before normalization? 
            # Re-computing raw adj is cheap.
            
            # Create raw target adj
            N = x.shape[0]
            target_adj = torch.eye(N)
            for link in graph.get("links", []):
                u, v = link["u"], link["v"]
                target_adj[u, v] = 1.0
                target_adj[v, u] = 1.0
                
            # Loss: BCEWithLogits
            # flatten
            loss = nn.functional.binary_cross_entropy_with_logits(z_zt.view(-1), target_adj.view(-1))
            
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item()
            count += 1
            
        if (epoch + 1) % 10 == 0:
            print(f"Epoch {epoch+1}/{epochs}, Avg Loss: {total_loss/count:.4f}")
            
    return model

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input JSON graph data")
    parser.add_argument("--output", required=True, help="Output JSON vector file")
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--dim", type=int, default=64, help="Embedding dimension")
    args = parser.parse_args()
    
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    
    if not os.path.exists(input_path):
        print(f"Input file not found: {input_path}")
        return

    # 1. Load Data
    raw_data = load_data(input_path)
    print(f"Loaded {len(raw_data)} graphs.")
    
    # 2. Build Vocabulary
    vocab = build_vocab(raw_data)
    print(f"Found {len(vocab)} unique node types.")
    
    # 3. Train (or just Initialize)
    # Even random weights give good structural embeddings (Random Projection GNN),
    # but training improves alignment.
    model = train_model(raw_data, vocab, epochs=args.epochs, embed_dim=args.dim)
    
    # 4. Generate Embeddings
    model.eval()
    output_dict = {}
    
    with torch.no_grad():
        for graph in raw_data:
            key = graph.get("key")
            x, adj = process_graph(graph, vocab)
            if x is None:
                continue
                
            # Get Graph Embedding
            vec = get_graph_embedding(model, x, adj)
            
            # Normalize (L2) - Crucial for Cosine Similarity later
            vec = torch.nn.functional.normalize(vec, p=2, dim=0)
            
            output_dict[key] = vec.tolist()
            
    # 5. Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_dict, f, indent=2) # Use indent for readability? Or compact?
        
    print(f"Saved {len(output_dict)} GNN vectors to {output_path}")

if __name__ == "__main__":
    main()
