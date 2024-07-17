from pathlib import Path
import ansible_runner
from pprint import pprint

base_path = Path(__file__).parent
with open("/home/leto/.ssh/pi_rsa") as f:
    ssh_key = f.read()
runner = ansible_runner.interface.run(playbook=str((base_path / "get_status.yml").absolute()), inventory= str((base_path / "EN325_inventory.yml").absolute()), ssh_key=ssh_key)
pprint(list(runner.events))