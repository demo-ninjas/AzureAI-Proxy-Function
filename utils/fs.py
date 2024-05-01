import os

def read_first_matching_file(file_name:str, search_paths:list[str], suffixes:list[str] = None) -> str:
    ## Check the paths in order to find a matching config file
    file_names = [file_name]
    if suffixes is not None:
        for suffix in suffixes:
            file_names.append(file_name + suffix)

    for path in search_paths:
        if path is None: continue
        
        for config_path in file_names:
            full_path = path + '/' + config_path
            if os.path.exists(full_path):
                with open(full_path, 'r') as f:
                    return f.read()

    return None

