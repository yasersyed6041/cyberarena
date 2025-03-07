from datetime import datetime, timezone
from marshmallow import ValidationError
from google.cloud import logging_v2
from netaddr import IPSet, IPNetwork, IPAddress, iter_iprange

from main_app_utilities.globals import BuildConstants, DatastoreKeyTypes, PubSub, get_current_timestamp_utc
from main_app_utilities.gcp.bucket_manager import BucketManager

__author__ = "Philip Huff"
__copyright__ = "Copyright 2022, UA Little Rock, Emerging Analytics Center"
__credits__ = ["Philip Huff"]
__license__ = "MIT"
__version__ = "1.0.0"
__maintainer__ = "Philip Huff"
__email__ = "pdhuff@ualr.edu"
__status__ = "Testing"


class UnitValidator:
    """
    Object validators perform higher-level validation than serializers. They look for common errors in configuration
    files and automatically fix them if possible. Otherwise, the validator throws an error with a message to let the
    user know the configuration needs to be fixed.
    """
    def __init__(self):
        self.config = None
        self.bucket_manager = BucketManager()
        self.network_map = {}

    def load(self, config):
        self.config = config
        if config.get('servers'):
            self._validate_network()
            self._add_firewall_rules()
        if config.get('assessment'):
            self._validate_assessment()
        return self.config

    def _validate_network(self):
        if 'networks' not in self.config:
            self.config['networks'] = [UnitBuildConstants.WORKOUT_DEFAULT_NETWORK_CONFIG]
        else:
            default_exists = False
            for network in self.config['networks']:
                if network['name'] == UnitBuildConstants.WORKOUT_DEFAULT_NETWORK_CONFIG['name']:
                    default_exists = True
                    if network['subnets'][0]['ip_subnet'] != "10.1.1.0/24":
                        raise ValidationError(f"The external network must use the subnet 10.1.1.0/24")
            if not default_exists:
                raise ValidationError(f"An external network is not included in the specification")

        for network in self.config['networks']:
            subnet = network['subnets'][0]['ip_subnet']
            current_network = IPSet(IPNetwork(subnet))
            for processed_network in self.network_map:
                processed_subnet = self.network_map[processed_network]
                if not current_network.isdisjoint(IPSet(IPNetwork(processed_subnet))):
                    raise ValidationError(f"Specification has overlapping networks {subnet} and {processed_subnet}. "
                                          f"Please correct this in the specification before building")
            self.network_map[network['name']] = subnet

        for server in self.config['servers']:
            for nic in server['nics']:
                network_name = nic['network']
                ip = nic['internal_ip']
                last_quad = ip.split(".")[-1]
                if network_name not in self.network_map:
                    raise ValidationError(f"{server['name']} is attempting to build in a network named {network_name} "
                                          f"which is not included in the specification")
                if not IPAddress(ip) in IPNetwork(self.network_map[network_name]):
                    raise ValidationError(f"{server['name']} uses an IP address {ip} that does not match its build "
                                          f"network subnet {self.network_map[network_name]}")
                if last_quad in ['0', '1', '254', '255']:
                    raise ValidationError(f"{server['name']} uses a reserved IP address {ip} for the cloud.")

    def _add_firewall_rules(self):
        firewall_rules = []
        for network in self.network_map:
            firewall_rule = {
                'name': 'allow-all-local',
                'network': network,
                'target_tags': [],
                'protocol': None,
                'ports': ['tcp/any', 'udp/any', 'icmp/any'],
                'source_ranges': [self.network_map[network]]
            }
            firewall_rules.append(firewall_rule)
        display_proxy_rule = {
            'name': 'allow-student-entry',
            'network': UnitBuildConstants.EXTERNAL,
            'target_tags': ['student-entry'],
            'protocol': None,
            'ports': ['tcp/80,8080,443'],
            'source_ranges': ['0.0.0.0/0']
        }
        firewall_rules.append(display_proxy_rule)
        self.config['firewall_rules'] = firewall_rules

    def _validate_assessment(self):
        server_names = [server['name'] for server in self.config['servers']] if self.config.get('servers') else []
        script_names = self.bucket_manager.get_scripts()
        for question in self.config.get('assessment'):
            if 'server' in question and question['server'] not in server_names:
                raise ValidationError(f"Invalid Server: Assessment uses a script on the server {question['server']} "
                                      f"that does not exist in the specification")
            if 'script' in question and question['script'] not in script_names:
                raise ValidationError(f"Invalid Script: Assessment uses the script {question['script']} that does "
                                      f"not exist in the cloud bucket for startup scripts")


class UnitBuildConstants:
    EXTERNAL = 'external'
    SUBNET_NAME = 'default'
    SUBNET_IP_SUBNET = '10.1.1.0/24'
    WORKOUT_DEFAULT_NETWORK_CONFIG = {
        'name': EXTERNAL,
        'subnets': [
            {
                'name': SUBNET_NAME,
                'ip_subnet': SUBNET_IP_SUBNET
            }
        ]
    }