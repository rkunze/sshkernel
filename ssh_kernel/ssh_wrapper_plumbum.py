import os
import time
import yaml

import paramiko
from plumbum.machines.paramiko_machine import ParamikoMachine

from .ssh_wrapper import SSHWrapper


class SSHWrapperPlumbum(SSHWrapper):
    '''
    A plumbum remote machine wrapper
    '''

    def __init__(self):
        self._remote = None
        self._connected = False
        self._host = ''

    def _append_command(self, cmd, marker):
        '''
        Append header/footer to `cmd`.

        Returns:
          str: new_command
        '''
        header = ''
        footer = '''
EXIT_CODE=$?
echo {marker}code: $EXIT_CODE
echo {marker}pwd: $(pwd)
echo {marker}env: $(cat -v <(env -0))
'''.format(marker=marker)

        full_command = '\n'.join([header, cmd, footer])

        return full_command

    def exec_command(self, cmd, print_function):
        '''
        Returns:
          int: exit_code
            * Return the last command exit_code
            * Return 1 if failed to execute a command

        Raises:
            plumbum.commands.processes.ProcessExecutionError: If exit_code is 0
        '''

        print_function('[INFO] host = {}\n'.format(self._host))

        timeout = None

        marker = str(time.time())
        full_command = self._append_command(cmd, marker)

        iterator = self._remote['bash'][
            '-c',
            full_command,
        ].popen().iter_lines()

        env_out = ''
        for (out, err) in iterator:
            line = out if out else err

            if line.startswith(marker):
                env_out += line.split(marker)[1]
            else:
                print_function(line)

        if env_out:
            return self.post_exec_command(env_out)
        else:
            return 1

    def connect(self, host):
        if self._remote:
            self.close()

        remote = self._build_remote(host)

        envdelta = {'PAGER': 'cat'}
        remote.env.update(envdelta)

        self._remote = remote
        self._connected = True
        self._host = host

    def _build_remote(self, host):
        (hostname, lookup) = self._init_ssh_config('~/.ssh/config', host)

        print('[DEBUG] host={host} hostname={hostname} other_conf={other_conf}'.format(
            host=host,
            hostname=hostname,
            other_conf=lookup,
        ))

        remote = ParamikoMachine(hostname, password=None, **lookup)

        return remote

    def close(self):
        self._connected = False
        self._remote.close()

    def interrupt(self):
        pass

    def isconnected(self):
        return self._connected

    # private methods
    def post_exec_command(self, env_out):
        '''Receive yaml string, update instance state with its value

        Return:
            int: exit_code
        '''
        env_at_footer = yaml.load(env_out)

        newdir = env_at_footer['pwd']
        newenv = env_at_footer['env']
        self.update_workdir(newdir)
        self.update_env(newenv)

        if 'code' in env_at_footer:
            return env_at_footer['code']
        else:
            print('[ERROR] Cannot parse exit_code. As a result, returing code=1')
            return 1

    def update_workdir(self, newdir):
        cwd = self.get_cwd()
        if newdir != cwd:
            self._remote.cwd.chdir(newdir)
            print('[DEBUG] new cwd: {}'.format(newdir))

    def get_cwd(self):
        return self._remote.cwd.getpath()._path

    def update_env(self, newenv):
        delimiter = '^@'
        parsed_newenv = dict([
            kv.split('=', 1) for kv in newenv.split(delimiter) if kv
        ])
        self._remote.env.update(parsed_newenv)

    def _init_ssh_config(self, filename, host):
        supported_fields = [
            'user',
            'port',
            'keyfile',
        ]
        conf = paramiko.config.SSHConfig()
        expanded_path = os.path.expanduser(filename)

        if os.path.exists(expanded_path):
            with open(expanded_path) as ssh_config:
                conf.parse(ssh_config)

        lookup = conf.lookup(host)

        if 'hostname' in lookup:
            hostname = lookup.pop('hostname')
        else:
            hostname = host

        if 'identityfile' in lookup:
            lookup['keyfile'] = lookup.pop('identityfile')
        if 'port' in lookup:
            lookup['port'] = int(lookup.pop('port'))

        keys_filtered = set(supported_fields) & set(lookup.keys())
        lookup_filtered = dict((k, lookup[k]) for k in keys_filtered)

        return (hostname, lookup_filtered)
