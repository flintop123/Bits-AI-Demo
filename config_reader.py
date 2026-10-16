import yaml
import os
import consul
from loghandler import getLogger

logger = getLogger()

def read_config(config_path=None):

    if config_path is None:
        # Get path relative to this Python file's directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, "config.yaml")

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as config_file:
        config = yaml.safe_load(config_file)
    
    return config