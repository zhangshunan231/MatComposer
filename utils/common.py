import json

def dict_to_str(d):
    return json.dumps(d)

def str_to_dict(s):
    try:
        return json.loads(s)
    except:
        return {}
