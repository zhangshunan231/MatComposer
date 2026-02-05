import random

def calculate_difference(params_a, params_b):
    """
    Calculate the delta between two parameter sets (B - A).
    params_a, params_b: dict { "NodeName.SocketName": value }
    Returns: dict (delta)
    """
    delta = {}
    for key, val_b in params_b.items():
        if key in params_a:
            val_a = params_a[key]
            delta[key] = _subtract_values(val_b, val_a)
    return delta

def extrapolate(start_params, delta_params, factor=1.0):
    """
    Apply delta to start_params with a factor.
    Returns: dict (new parameters)
    """
    new_params = start_params.copy()
    for key, d_val in delta_params.items():
        if key in new_params:
            new_params[key] = _add_values(new_params[key], d_val, factor)
    return new_params

def apply_noise(params, intensity=0.1):
    """
    Apply random Gaussian noise to parameters.
    """
    new_params = params.copy()
    for key, val in new_params.items():
        new_params[key] = _add_noise(val, intensity)
    return new_params

def _subtract_values(b, a):
    if isinstance(b, (int, float)) and isinstance(a, (int, float)):
        return b - a
    elif isinstance(b, (list, tuple)) and isinstance(a, (list, tuple)):
        # Handle Vector/Color (component-wise)
        return [v_b - v_a for v_b, v_a in zip(b, a)]
    return 0

def _add_values(start, delta, factor):
    if isinstance(start, (int, float)):
        # Delta for float is float
        if isinstance(delta, (int, float)):
             return start + (delta * factor)
        return start
    elif isinstance(start, (list, tuple)):
        # Delta for list is list
        if isinstance(delta, (list, tuple)):
            return [s + (d * factor) for s, d in zip(start, delta)]
        return start
    return start

def _add_noise(val, intensity):
    if isinstance(val, (int, float)):
        # Range check: Roughness 0-1, etc. But here we just do math.
        # Assume reasonable scale.
        noise = random.gauss(0, intensity)
        return val + noise
    elif isinstance(val, (list, tuple)):
        return [v + random.gauss(0, intensity) for v in val]
    return val
