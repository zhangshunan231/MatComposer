# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

import json

def dict_to_str(d):
    return json.dumps(d)

def str_to_dict(s):
    try:
        return json.loads(s)
    except:
        return {}
