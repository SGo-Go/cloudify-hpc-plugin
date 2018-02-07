########
# Copyright (c) 2018 HLRS - hpcgogol@hlrs.de
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

""" Holds the Torque functions """
import string
import random

from hpc_plugin.utilities  import shlex_quote
from hpc_plugin.cli_client import CliClient as SshClient

def submit_job(ssh_client, name, job_settings, is_singularity, logger):
    """
    Sends a job to the HPC using Torque

    @type ssh_client: SshClient
    @param ssh_client: SSH client connected to an HPC login node
    @type name: string
    @param name: name of the job in Torque
    @type job_settings: dictionary
    @param job_settings: dictionary with the job options
    @type is_singularity: bool
    @param is_singularity: True if the job is in a container
    @rtype string
    @return Torque's job name sent. None if an error arise.
    """
    if not isinstance(ssh_client, SshClient) or not ssh_client.is_open():
        logger.error("SSH Client can't be used")
        return False

    if is_singularity:
        # get script data and escape for echo
        script_data = get_container_script(name, job_settings)
        # In theory script_data should be escaped to prepare it for echo
        # but as the script is generated programmatically, we know for sure
        # that is not necessary. Nevertheless keep commented the code
        # in case it is needed in the future.
        #    .replace("\\", "\\\\") \
        #    .replace("$", "\\$") \
        #    .replace("`", "\\`") \
        #    .replace('"', '\\"')
        if script_data is None:
            logger.error("Singularity Script malformed")
            return False

        output, exit_code = ssh_client.send_command("echo '" + script_data +
                                                    "' > " + name +
                                                    ".script",
                                                    wait_result=True)
        if exit_code is not 0:
            logger.error(
                "Singularity script couldn't be created, exited with code " +
                str(exit_code) + ": " + output)
            return False
        settings = {
            "type": "TORQUE",
            "command": name + ".script"
        }
    else:
        settings = job_settings

    response = get_call(name, settings)
    if 'error' in response:
        logger.error(
            "Couldn't create the call to send the job: " + response['error'])
        return False

    call = response['call']
    output, exit_code = ssh_client.send_command(call, wait_result=True)
    if exit_code is not 0:
        logger.error("Call '" + call + "' exited with code " +
                     str(exit_code) + ": " + output)
        return False
    return True


def clean_job_aux_files(ssh_client, name,
                        job_settings,
                        is_singularity,
                        logger):
    """
    Cleans no more needed job files in the HPC

    @type ssh_client: SshClient
    @param ssh_client: SSH client connected to an HPC login node
    @type name: string
    @param name: name of the job in Torque
    @type job_settings: dictionary
    @param job_settings: dictionary with the job options
    @type is_singularity: bool
    @param is_singularity: True if the job is in a container
    @rtype string
    @return Torque's job name stopped. None if an error arise.
    """
    if not isinstance(ssh_client, SshClient) or not ssh_client.is_open():
        logger.error("SSH Client can't be used")
        return False

    if is_singularity:
        return ssh_client.send_command("rm " + name + ".script")
    return True


def stop_job(ssh_client, name, job_settings, is_singularity, logger):
    """
    Stops a job from the HPC using Torque

    @type ssh_client: SshClient
    @param ssh_client: SSH client connected to an HPC login node
    @type name: string
    @param name: name of the job in Torque
    @type job_settings: dictionary
    @param job_settings: dictionary with the job options
    @type is_singularity: bool
    @param is_singularity: True if the job is in a container
    @rtype string
    @return Torque's job name stopped. None if an error arise.
    """
    if not isinstance(ssh_client, SshClient) or not ssh_client.is_open():
        logger.error("SSH Client can't be used")
        return False

    call = r"qselect -N {} | xargs qdel".format(shlex_quote(name))

    return ssh_client.send_command(call)


def get_jobids_by_name(ssh_client, job_names):
    """
    Get JobID from qstat command

    This function uses qstat command to query Torque. In this case Torque
    strongly recommends that the code should performs these queries once
    every 60 seconds or longer. Using these commands contacts the master
    controller directly, the same process responsible for scheduling all
    work on the cluster. Polling more frequently, especially across all
    users on the cluster, will slow down response times and may bring
    scheduling to a crawl. Please don't.
    """
    # ? TODO(emepetres) set first day of consulting
    # r'for i in "windturb7.5" j023; do echo qselect -N $i|awk "{printf \"$i,%s\n\", $1}"; done'
    # r"qstat -i `echo {} | xargs -n 1 qselect -N` | tail -n+6 | awk '{{ printf \"%s %s\n\",$4,$1 }}'".\
    call = "qstat -i `echo {} | xargs -n 1 qselect -N` | tail -n+6 | awk '{{ print $4 \" \" $1 }}'".\
        format( shlex_quote(' '.join(map(shlex_quote, job_names))) )
    output, exit_code = ssh_client.send_command(call, wait_result=True)

    ids = {}
    if exit_code == 0:
        ids = parse_qstat(output)

    return ids


def get_status(ssh_client, job_ids):
    """
    Get Status from qstat command

    This function uses qstat command to query Torque. In this case Torque
    strongly recommends that the code should performs these queries once
    every 60 seconds or longer. Using these commands contacts the master
    controller directly, the same process responsible for scheduling all
    work on the cluster. Polling more frequently, especially across all
    users on the cluster, will slow down response times and may bring
    scheduling to a crawl. Please don't.
    """
    # TODO(emepetres) set first day of consulting(qstat only check current day)
    #qstat  | tail -n+3 | awk '{ printf "%s,%s\n",$1,$5 }'
    # r"qstat -i {} | tail -n+6 | awk '{{ printf \"%s %s\n\",$1,$10 }}'".\
    call = "qstat -i {} | tail -n+6 | awk '{{ print $1 \" \" $10 }}'".\
        format( ' '.join(job_ids) )
    output, exit_code = ssh_client.send_command(call, wait_result=True)

    states = {}
    if exit_code == 0:
        states = parse_qstat(output)

    return states


def parse_qstat(qstat_output):
    """ Parse two colums qstat entries into a dict """
    jobs = qstat_output.splitlines()
    parsed = {}
    if jobs and (len(jobs) > 1 or jobs[0] is not ''):
        for job in jobs:
            first, second = job.strip().split()
            parsed[first] = second

    return parsed


def get_container_script(name, job_settings):
    """
    Creates a Torque script to run Singularity

    @type name: string
    @param name: name of the job in Torque
    @type job_settings: dictionary
    @param job_settings: dictionary with the container job options
    @rtype string
    @return string with the Torque script for submitting via `qsub`. None if an error arise.
    """
    # check input information correctness
    if not isinstance(job_settings, dict) or not isinstance(name,
                                                            basestring):
        # TODO(emepetres): Raise error
        return None

    if 'image' not in job_settings or 'command' not in job_settings or\
            'max_time' not in job_settings:
        # TODO(emepetres): Raise error
        return None

    script = '#!/bin/bash -l\n\n'
    # TODO: why commented out???
    # script += '#PBS --parsable\n'
    # script += '#PBS -J "' + name + '"\n'

    resources_request = ''
    if 'nodes' in job_settings:
        resources_request += "nodes=" + str(job_settings['nodes'])

    if 'tasks_per_node' in job_settings:
        if len(resources_request) > 0:
            resources_request += ':ppn=' + str(job_settings['tasks_per_node'])
        else:
            logger.error("")

    if len(resources_request) > 0:
        script += '#PBS -l ' + resources_request + '\n'

    if 'max_time' in job_settings:
        script += '#PBS -l walltime=' + str(job_settings['max_time']) + '\n'

    script += '\n'

    # first set modules
    if 'modules' in job_settings:
        script += 'module load'
        for module in job_settings['modules']:
            script += ' ' + module
        script += '\n'

    if 'home' in job_settings and job_settings['home'] != '':
        script += 'cd ' + job_settings['home'] + '\n'

    script += '\nmpirun singularity exec '

    #TODO: comment?
    if 'volumes' in job_settings:
        for volume in job_settings['volumes']:
            script += '-B ' + volume + ' '
    # add executable and arguments
    script += job_settings['image'] + ' ' + job_settings['command'] + '\n'

    # disable output
    # script += ' >/dev/null 2>&1';

    return script


def get_call(name, job_settings):
    """
    Generates Torque command line as a string

    @type name: string
    @param name: name of the job in Torque
    @type job_settings: dictionary
    @param job_settings: dictionary with the job options
    @rtype string
    @return string to call Torque with its parameters. None if an error arise.
    """
    # check input information correctness
    if not isinstance(job_settings, dict) or not isinstance(name,
                                                            basestring):
        return {'error': "Incorrect inputs"}

    if 'type' not in job_settings or 'command' not in job_settings:
        return {'error': "'type' and 'command' " +
                "must be defined in job settings"}

    # first set modules
    torque_call = ''
    if 'modules' in job_settings:
        torque_call += 'module load'
        for module in job_settings['modules']:
            torque_call += ' ' + module
        torque_call += '; '

    if job_settings['type'] == 'TORQUE':
        # qsub command plus job name
        torque_call += "qsub -V -N {}".format(shlex_quote(name))
    else:
        return {'error': "Job type '" + job_settings['type'] +
                "'not supported"}

    # Torque settings
    resources_request = ''
    if 'nodes' in job_settings:
        resources_request += "nodes=" + str(job_settings['nodes'])

    if 'tasks_per_node' in job_settings:
        if len(resources_request) > 0:
            resources_request += ':ppn=' + str(job_settings['tasks_per_node'])
        else:
            logger

    if 'max_time' in job_settings:
        if len(resources_request) > 0:
            resources_request += ','
        resources_request += 'walltime=' + str(job_settings['max_time'])
    if len(resources_request) > 0:
        torque_call += ' -l ' + resources_request

    # add executable and arguments
    torque_call += ' ' + job_settings['command']

    # disable output
    # torque_call += ' >/dev/null 2>&1';

    return {'call': torque_call}


def get_random_name(base_name):
    """ Get a random name with a prefix """
    return base_name + '_' + __id_generator()


def __id_generator(size=6, chars=string.digits + string.ascii_letters):
    return ''.join(random.SystemRandom().choice(chars) for _ in range(size))
