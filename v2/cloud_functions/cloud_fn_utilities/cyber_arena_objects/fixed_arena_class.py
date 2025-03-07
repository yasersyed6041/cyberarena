import logging
import random
import string
from datetime import datetime, timezone
from netaddr import IPNetwork, IPAddress, iter_iprange

from google.cloud import logging_v2

from cloud_fn_utilities.gcp.cloud_env import CloudEnv
from cloud_fn_utilities.gcp.vpc_manager import VpcManager
from cloud_fn_utilities.gcp.datastore_manager import DataStoreManager
from cloud_fn_utilities.gcp.firewall_rule_manager import FirewallManager
from cloud_fn_utilities.gcp.pubsub_manager import PubSubManager
from cloud_fn_utilities.gcp.compute_manager import ComputeManager
from cloud_fn_utilities.globals import DatastoreKeyTypes, PubSub, BuildConstants, FixedArenaClassStates, \
    get_current_timestamp_utc
from cloud_fn_utilities.state_managers.fixed_arena_class_states import FixedArenaClassStateManager
from cloud_fn_utilities.server_specific.firewall_server import FirewallServer
from cloud_fn_utilities.server_specific.fixed_arena_workspace_proxy import FixedArenaWorkspaceProxy
from cloud_fn_utilities.server_specific.agent_configuration import Agent

__author__ = "Philip Huff"
__copyright__ = "Copyright 2022, UA Little Rock, Emerging Analytics Center"
__credits__ = ["Philip Huff", "Bryce Ebsen", "Ryan Ebsen", "Andrew Bomberger"]
__license__ = "MIT"
__version__ = "1.0.0"
__maintainer__ = "Philip Huff"
__email__ = "pdhuff@ualr.edu"
__status__ = "Testing"


class FixedArenaClass:
    def __init__(self, build_id, debug=False, force=False, env_dict=None):
        self.fixed_arena_class_id = build_id
        self.debug = debug
        self.force = force
        self.env = CloudEnv(env_dict=env_dict) if env_dict else CloudEnv()
        self.env_dict = self.env.get_env()
        log_client = logging_v2.Client()
        log_client.setup_logging()
        self.s = FixedArenaClassStates
        self.pubsub_manager = PubSubManager(PubSub.Topics.CYBER_ARENA.value, env_dict=self.env_dict)
        self.state_manager = FixedArenaClassStateManager(initial_build_id=self.fixed_arena_class_id)
        self.firewall_manager = FirewallManager(env_dict=self.env_dict)
        self.ds = DataStoreManager(key_type=DatastoreKeyTypes.FIXED_ARENA_CLASS, key_id=self.fixed_arena_class_id)
        self.fixed_arena_class = self.ds.get()
        if not self.fixed_arena_class:
            logging.error(f"The datastore record for {self.fixed_arena_class_id} no longer exists!")
            raise LookupError

        fixed_arena_id = self.fixed_arena_class.get('parent_id', None)
        self.ds_fixed_arena = DataStoreManager(key_type=DatastoreKeyTypes.FIXED_ARENA, key_id=fixed_arena_id)
        self.fixed_arena = self.ds_fixed_arena.get()
        self.fixed_arena_workspace_ids = self._get_fixed_arena_workspace_ids()
        ip_range = BuildConstants.Networks.Reservations.FIXED_ARENA_WORKOUT_SERVER_RANGE
        self.ip_reservations = list(iter_iprange(ip_range[0], ip_range[1]))
        self.next_reservation = 0

    def build(self):
        # If a class already exists and a force delete is not set, this function will fail with a value error.
        self._set_active_class()

        if not self.state_manager.get_state():
            self.state_manager.state_transition(self.s.START)

        # Create datastore records for each workspace under the key type fixed-arena-workout
        self.fixed_arena_workspace_ids = self._create_workspace_records()

        # Build attack Pubsub topics if needed
        if self.fixed_arena_class['add_attacker']:
            Agent(parent_id=self.fixed_arena_class_id, env_dict=self.env_dict).create_topics()

        # Build workspace servers
        if self.state_manager.get_state() <= self.s.BUILDING_SERVERS.value:
            self.state_manager.state_transition(self.s.BUILDING_SERVERS)
            for ws_id in self.fixed_arena_workspace_ids:
                ws_servers = []
                for server_template in self.fixed_arena_class['workspace_servers']:
                    server = server_template.copy()
                    server_name = f"{ws_id}-{server['name']}"
                    server['parent_id'] = ws_id
                    server['parent_build_type'] = BuildConstants.BuildType.FIXED_ARENA_WORKSPACE
                    server['fixed_arena_class_id'] = self.fixed_arena_class_id
                    server['fixed_arena_id'] = self.fixed_arena_class['parent_id']
                    if 'nics' not in server:
                        server['nics'] = self._get_workspace_network_config()
                    self.ds.put(server, key_type=DatastoreKeyTypes.SERVER, key_id=server_name)
                    if self.debug:
                        ComputeManager(server_name=server_name, env_dict=self.env_dict).build()
                    else:
                        self.pubsub_manager.msg(handler=PubSub.Handlers.BUILD,
                                                action=str(PubSub.BuildActions.SERVER.value),
                                                key_type=str(DatastoreKeyTypes.FIXED_ARENA_CLASS),
                                                build_id=str(self.fixed_arena_class_id),
                                                server_name=server_name)
                    ws_servers.append(server)

                # Build workspace attack machine if needed
                if self.fixed_arena_class['add_attacker']:
                    agent = Agent(build_id=ws_id, parent_id=self.fixed_arena_class_id, env_dict=self.env_dict).config()
                    agent['parent_build_type'] = BuildConstants.BuildType.FIXED_ARENA_WORKSPACE
                    agent['fixed_arena_class_id'] = self.fixed_arena_class_id
                    agent['fixed_arena_id'] = self.fixed_arena_class['parent_id']
                    agent['nics'] = self._get_workspace_network_config()
                    agent['nics'][0]['external_nat'] = True
                    agent_name = f'{ws_id}-{agent["name"]}'
                    self.ds.put(agent, key_type=DatastoreKeyTypes.SERVER, key_id=agent_name)
                    if self.debug:
                        ComputeManager(server_name=agent_name, env_dict=self.env_dict).build()
                    else:
                        self.pubsub_manager.msg(handler=PubSub.Handlers.BUILD,
                                                action=str(PubSub.BuildActions.SERVER.value),
                                                key_type=str(DatastoreKeyTypes.FIXED_ARENA_CLASS),
                                                build_id=str(self.fixed_arena_class_id),
                                                server_name=agent_name)
                    ws_servers.append(agent)

                # Store the server information with IP addresses back with each fixed arena workout before looping
                ws_record = self.ds.get(key_type=DatastoreKeyTypes.FIXED_ARENA_WORKSPACE, key_id=ws_id)
                ws_record['servers'] = ws_servers
                self.ds.put(ws_record, key_type=DatastoreKeyTypes.FIXED_ARENA_WORKSPACE, key_id=ws_id)

            # Now build the Workspace Proxy Server
            if self.state_manager.get_state() <= self.s.BUILDING_STUDENT_ENTRY.value:
                self.state_manager.state_transition(self.s.BUILDING_STUDENT_ENTRY)
                if self.debug:
                    FixedArenaWorkspaceProxy(build_id=self.fixed_arena_class_id,
                                             workspace_ids=self.fixed_arena_workspace_ids,
                                             env_dict=self.env_dict).build()
                else:
                    self.pubsub_manager.msg(handler=PubSub.Handlers.BUILD,
                                            action=str(PubSub.BuildActions.FIXED_ARENA_WORKSPACE_PROXY.value),
                                            build_id=str(self.fixed_arena_class_id),
                                            workspace_ids=' '.join(self.fixed_arena_workspace_ids))

        if not self.state_manager.are_server_builds_finished():
            self.state_manager.state_transition(self.s.BROKEN)
            logging.error(f"Fixed Arena {self.fixed_arena_class_id}: Timed out waiting for server builds to "
                          f"complete!")
        else:
            self.state_manager.state_transition(self.s.READY)
            logging.info(f"Finished building Fixed Arena {self.fixed_arena_class_id}!")

    def start(self):
        self.state_manager.state_transition(self.s.START)
        servers_to_start = self._get_servers()

        for server in servers_to_start:
            if self.debug:
                ComputeManager(server, env_dict=self.env_dict).start()
            else:
                self.pubsub_manager.msg(handler=PubSub.Handlers.CONTROL, action=str(PubSub.Actions.START.value),
                                        build_id=server,
                                        cyber_arena_object=str(PubSub.CyberArenaObjects.SERVER.value))

        if not self.state_manager.are_servers_started():
            self.state_manager.state_transition(self.s.BROKEN)
            logging.error(f"Fixed Arena {self.fixed_arena_class_id}: Timed out waiting for server builds to "
                          f"complete!")
        else:
            self.state_manager.state_transition(self.s.RUNNING)
            logging.info(f"Finished starting the Fixed Arena Workout: {self.fixed_arena_class_id}!")

    def stop(self):
        self.state_manager.state_transition(self.s.STOPPING)
        servers_to_stop = self._get_servers()

        for server in servers_to_stop:
            if self.debug:
                ComputeManager(server, env_dict=self.env_dict).stop()
            else:
                self.pubsub_manager.msg(handler=PubSub.Handlers.CONTROL, action=str(PubSub.Actions.STOP.value),
                                        build_id=server,
                                        cyber_arena_object=str(PubSub.CyberArenaObjects.SERVER.value))

        if not self.state_manager.are_servers_stopped():
            self.state_manager.state_transition(self.s.BROKEN)
            logging.error(f"Fixed Arena {self.fixed_arena_class_id}: Timed out waiting for server builds to "
                          f"complete!")
        else:
            self.state_manager.state_transition(self.s.STOPPED)
            logging.info(f"Finished starting the Fixed Arena Workout: {self.fixed_arena_class_id}!")

    def delete(self):
        # First stop the servers because some servers are permanent and would otherwise continue running.
        # self.stop()
        self.state_manager.state_transition(self.s.DELETING_SERVERS)
        servers_to_delete = self._get_servers(for_deletion=True)

        # Delete Agent PubSub subscription/topic
        if self.fixed_arena_class.get('add_attacker'):
            Agent(parent_id=self.fixed_arena_class_id, env_dict=self.env_dict).delete()

        for server in servers_to_delete:
            if self.debug:
                try:
                    ComputeManager(server, env_dict=self.env_dict).delete()
                except LookupError:
                    logging.error(f"Fixed Arena {self.fixed_arena_class_id}: Could not find server record "
                                  f"for {server}. Ignoring server ...")
                    continue
            else:
                self.pubsub_manager.msg(handler=PubSub.Handlers.CONTROL, action=str(PubSub.Actions.DELETE.value),
                                        build_id=server,
                                        cyber_arena_object=str(PubSub.CyberArenaObjects.SERVER.value))

        if not self.state_manager.are_servers_deleted():
            self.state_manager.state_transition(self.s.BROKEN)
            logging.error(f"Fixed Arena {self.fixed_arena_class_id}: Timed out waiting for server deletions to "
                          f"complete!")
        else:
            self.state_manager.state_transition(self.s.DELETED)
            logging.info(f"Finished deleting the Fixed Arena Workout: {self.fixed_arena_class_id}!")
        self._clear_active_class()

    def nuke(self):
        servers_to_nuke = self._get_servers(for_deletion=True)

        for server in servers_to_nuke:
            if self.debug:
                try:
                    ComputeManager(server, env_dict=self.env_dict).nuke()
                except LookupError:
                    continue
            else:
                self.pubsub_manager.msg(handler=PubSub.Handlers.CONTROL, action=str(PubSub.Actions.NUKE.value),
                                        build_id=server,
                                        cyber_arena_object=str(PubSub.CyberArenaObjects.SERVER.value))

        if not self.state_manager.are_server_builds_finished():
            self.state_manager.state_transition(self.s.BROKEN)
            logging.error(f"Fixed Arena {self.fixed_arena_class_id}: Timed out waiting for server builds to "
                          f"complete!")
        else:
            self.state_manager.state_transition(self.s.READY)
            logging.info(f"Finished nuking Fixed Arena {self.fixed_arena_class_id}!")

    def mark_broken(self):
        self.fixed_arena_class['state'] = self.s.BROKEN.value
        self.ds.put(self.fixed_arena_class)

    def _get_servers(self, for_deletion=False):
        display_proxy = f"{self.fixed_arena_class_id}-{BuildConstants.Servers.FIXED_ARENA_WORKSPACE_PROXY}"
        servers = [display_proxy]
        if not for_deletion:
            for server in self.fixed_arena_class['fixed_arena_servers']:
                server_name = f"{self.fixed_arena_class['parent_id']}-{server}"
                servers.append(server_name)
        for ws_id in self.fixed_arena_workspace_ids:
            ws_ds = DataStoreManager(key_type=DatastoreKeyTypes.FIXED_ARENA_WORKSPACE, key_id=ws_id)
            ws_servers = ws_ds.get_servers()
            for ws_server in ws_servers:
                server_name = f"{ws_server['parent_id']}-{ws_server['name']}"
                servers.append(server_name)
        return servers

    def _get_fixed_arena_workspace_ids(self):
        workspaces = DataStoreManager().get_children(child_key_type=DatastoreKeyTypes.FIXED_ARENA_WORKSPACE,
                                                     parent_id=self.fixed_arena_class['id'])
        workspace_ids = []
        for workspace in workspaces:
            workspace_ids.append(workspace.key.name)
        return workspace_ids

    def _create_workspace_records(self):
        workspace_datastore = DataStoreManager()
        registration_required = self.fixed_arena_class['workspace_settings'].get('registration_required', False)
        if registration_required:
            student_emails = self.fixed_arena_class['workspace_settings']['student_emails']
            student_names = self.fixed_arena_class['workspace_settings']['student_names']
            count = min(self.env.max_workspaces, len(student_names))
        else:
            count = min(self.env.max_workspaces, self.fixed_arena_class['workspace_settings']['count'])

        workspace_ids = []
        for i in range(count):
            id = ''.join(random.choice(string.ascii_lowercase) for j in range(10))
            workspace_record = {
                'id': id,
                'parent_id': self.fixed_arena_class_id,
                'parent_build_type': BuildConstants.BuildType.FIXED_ARENA_CLASS,
                'fixed_arena_id': self.fixed_arena_class['parent_id'],
                'build_type': BuildConstants.BuildType.FIXED_ARENA_WORKSPACE,
                'creation_timestamp': get_current_timestamp_utc(),
                'registration_required': registration_required,
            }
            if registration_required:
                workspace_record['student_email'] = student_emails[i]
                workspace_record['student_name'] = student_names[i]
            workspace_datastore.put(workspace_record, key_type=DatastoreKeyTypes.FIXED_ARENA_WORKSPACE, key_id=id)
            workspace_ids.append(id)
        return workspace_ids

    def _get_workspace_network_config(self):
        network_config = [{
            'network': BuildConstants.Networks.GATEWAY_NETWORK_NAME,
            'internal_ip': str(self.ip_reservations[self.next_reservation]),
            'subnet_name': 'default',
            'external_nat': False
        }]
        self.next_reservation += 1
        return network_config

    def _set_active_class(self):
        active_class = self.fixed_arena.get('active_class', None)
        if active_class:
            if self.force:
                FixedArenaClass(build_id=active_class, debug=True, env_dict=self.env_dict).delete()
            else:
                logging.error(
                    f"Fixed Arena Class {self.fixed_arena_class_id}: Cannot build fixed arena! The active class "
                    f"with id {active_class} already exists!")
                raise ValueError

        # TODO: Fix race condition
        self.fixed_arena['active_class'] = self.fixed_arena_class_id
        self.ds_fixed_arena.put(self.fixed_arena)

    def _clear_active_class(self):
        self.fixed_arena['active_class'] = None
        self.ds_fixed_arena.put(self.fixed_arena)
