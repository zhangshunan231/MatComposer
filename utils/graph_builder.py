import bpy
import mathutils

def clean_tree(tree):
    """Remove all nodes except 'Material Output'."""
    nodes = tree.nodes
    for node in nodes:
        if node.type != 'OUTPUT_MATERIAL':
            nodes.remove(node)
    
    # Ensure Material Output exists if it was missing
    output_node = None
    for node in nodes:
        if node.type == 'ShaderNodeOutputMaterial':
            output_node = node
            break
            
    if not output_node:
        output_node = tree.nodes.new(type='ShaderNodeOutputMaterial')
        output_node.location = (300, 0)
        output_node.label = "Material Output"
        output_node.name = "Material Output"
    
    return output_node

def create_node(tree, type_name, location, label=None, name=None):
    """Create a node safely."""
    try:
        node = tree.nodes.new(type=type_name)
        node.location = location
        if label:
            node.label = label
        if name:
            node.name = name
        return node
    except Exception as e:
        print(f"Error creating node {type_name}: {e}")
        return None

def _get_node_fuzzy(nodes, name):
    """Find a node by name, case-insensitive."""
    node = nodes.get(name)
    if node:
        return node
    
    # Try case-insensitive match
    name_lower = name.lower()
    for n in nodes:
        if n.name.lower() == name_lower:
            return n
            
    # Special handling for "Material Output" variations
    if "output" in name_lower:
        for n in nodes:
            if n.type == 'OUTPUT_MATERIAL':
                return n
                
    return None

def link_nodes(tree, from_node_name, from_socket_name, to_node_name, to_socket_name):
    """Link two nodes by name and socket name."""
    nodes = tree.nodes
    links = tree.links
    
    from_node = _get_node_fuzzy(nodes, from_node_name)
    to_node = _get_node_fuzzy(nodes, to_node_name)
    
    if not from_node:
        print(f"Error: Could not find source node '{from_node_name}'")
        return False
    if not to_node:
        print(f"Error: Could not find target node '{to_node_name}'")
        return False

    # Find sockets
    from_socket = from_node.outputs.get(from_socket_name)
    to_socket = to_node.inputs.get(to_socket_name)
    
    if not from_socket:
        print(f"Error: Output socket '{from_socket_name}' not found on '{from_node_name}'")
        # Fallback: try to find by case-insensitive name
        for out in from_node.outputs:
            if out.name.lower() == from_socket_name.lower():
                from_socket = out
                break
    
    if not to_socket:
        print(f"Error: Input socket '{to_socket_name}' not found on '{to_node_name}'")
        # Fallback: try to find by case-insensitive name
        for inp in to_node.inputs:
             if inp.name.lower() == to_socket_name.lower():
                to_socket = inp
                break
    
    if from_socket and to_socket:
        links.new(from_socket, to_socket)
        return True
    return False

def set_input_value(node, socket_name, value):
    """Set value for a node input socket. Handles Float, Vector, and RGBA types."""
    if not node:
        return

    # Special handling for ColorRamp Stops (Property, not Input)
    if node.type == 'ShaderNodeValToRGB' and socket_name == 'Stops':
        try:
            # value is list of {"position": 0.0, "color": [...]}
            elements = node.color_ramp.elements
            # Clear existing (except first/last usually can't be deleted easily in UI but API allows?)
            # API allows removing all but one usually.
            # But let's just resize/overwrite.
            
            # Ensure enough elements
            while len(elements) < len(value):
                elements.new(1.0)
            while len(elements) > len(value):
                elements.remove(elements[-1])
                
            for i, stop_data in enumerate(value):
                elem = elements[i]
                elem.position = stop_data.get("position", i / max(1, len(value)-1))
                elem.color = stop_data.get("color", [0,0,0,1])
            return
        except Exception as e:
            print(f"Error setting ColorRamp stops: {e}")
            return

    # Map legacy/LLM names to Blender 4.0+ names
    socket_map = {
        "Principled BSDF": {
            "Subsurface": "Subsurface Weight",
            "Subsurface IOR": "IOR", 
            "Specular": "Specular IOR Level",
            "Transmission": "Transmission Weight",
            "Coat": "Coat Weight",
            "Sheen": "Sheen Weight",
            "Emission": "Emission Color",
        }
    }
    
    candidates = [socket_name]
    if node.name == "Principled BSDF" or node.type == "ShaderNodeBsdfPrincipled":
        mapping = socket_map.get("Principled BSDF")
        if socket_name in mapping:
            # Prioritize the mapped name (likely 4.0+)
            candidates.insert(0, mapping[socket_name])

    socket = None
    for name in candidates:
        if not name: continue
        socket = node.inputs.get(name)
        if socket:
            break
    
    # Fallback: fuzzy search
    if not socket:
        target_lower = socket_name.lower()
        for inp in node.inputs:
            if inp.name.lower() == target_lower:
                socket = inp
                break

    # 4.0 Specific fallback for Specular
    if not socket and "specular" in socket_name.lower():
         # Try finding anything with Specular
         for inp in node.inputs:
             if "specular" in inp.name.lower() and "tint" not in inp.name.lower():
                 socket = inp
                 break

    if not socket:
        print(f"Error: Socket '{socket_name}' not found on '{node.name}' (Tried: {candidates})")
        return
        
    try:
        if isinstance(value, (int, float)):
            socket.default_value = value
        elif isinstance(value, list) or isinstance(value, tuple):
            if len(value) == 3: # Vector
                socket.default_value = value
            elif len(value) == 4: # RGBA
                socket.default_value = value
            else:
                print(f"Warning: Unexpected list length for {socket_name}: {value}")
        else:
             print(f"Warning: Unknown value type for {socket_name}: {type(value)}")
    except Exception as e:
        print(f"Error setting value for {socket_name}: {e}")

def get_node_parameters(tree):
    """
    Extract all editable input parameters from the node tree.
    Returns: dict { "NodeName.SocketName": value }
    """
    params = {}
    if not tree:
        return params
        
    for node in tree.nodes:
        # Skip output nodes
        if node.type == 'OUTPUT_MATERIAL':
            continue
            
        for input_socket in node.inputs:
            # We only care about unconnected sockets that have values
            if not input_socket.is_linked:
                # Store if it's a value we can manipulate (Float, Vector, Color)
                val = None
                try:
                    # Access default_value directly. 
                    # Note: Some sockets (like Shader) don't have a simple default_value we can tween easily 
                    # without checking type, but for PBR parameters it works.
                    val = input_socket.default_value
                    
                    # Convert Blender types to Python types for JSON/Math
                    if hasattr(val, 'to_tuple'): # Color/Vector
                        val = list(val)
                    elif isinstance(val, (int, float)):
                        pass
                    else:
                        continue # Skip types we don't handle
                        
                    key = f"{node.name}.{input_socket.name}"
                    params[key] = val
                except:
                    continue
    return params

def apply_parameters(tree, params):
    """
    Apply a dictionary of parameters to the tree.
    """
    if not tree:
        return
        
    for key, value in params.items():
        try:
            node_name, socket_name = key.split('.', 1)
            node = tree.nodes.get(node_name)
            if node:
                set_input_value(node, socket_name, value)
        except Exception as e:
            print(f"Error applying param {key}: {e}")

def build_graph(tree, data):
    """
    Build the entire node graph from JSON data.
    """
    if not tree:
        return

    # Clear existing nodes (except output if we want to be safe, but clean_tree handles it)
    # Actually, let's reuse clean_tree
    clean_tree(tree)
    
    # But clean_tree keeps one output node. If the JSON defines its own output node, we might have duplicates 
    # if we are not careful. However, usually we just want to ensure one output exists.
    # The JSON schema usually generates components. 
    
    components = data.get("components", [])
    links = data.get("links", [])
    
    # Pass 1: Create Nodes
    x_pos = -300
    y_pos = 0
    
    for comp in components:
        node_type = comp.get("node_type")
        name = comp.get("name")
        inputs = comp.get("inputs", {})
        
        # If it's the Material Output, try to find the existing one
        if node_type == 'ShaderNodeOutputMaterial':
            # We already have one from clean_tree
            continue
            
        # Layout logic (very simple)
        x_pos -= 300
        if x_pos < -1200:
            x_pos = -300
            y_pos -= 300
            
        # Create
        node = create_node(tree, node_type, (x_pos, y_pos), label=name, name=name)
        
        if node:
            # Set inputs
            for socket_name, value in inputs.items():
                set_input_value(node, socket_name, value)
                
    # Pass 2: Links
    for link in links:
        link_nodes(
            tree, 
            link["from_node"], 
            link["from_socket"], 
            link["to_node"], 
            link["to_socket"]
        )
