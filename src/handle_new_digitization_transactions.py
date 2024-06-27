#!/usr/bin/env python3

"""Create Asana tasks for every new transaction in Aeon.

Requires encrypted environment variables:
    ENV
    APP_CONFIG_PATH
"""

import traceback
from os import environ

import asana
import boto3
from requests import Session


class AeonClient(object):
    def __init__(self, baseurl, access_key):
        self.session = Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'AeonClient/0.1',
            'X-AEON-API-KEY': access_key
        })
        self.baseurl = baseurl

    def get(self, url):
        full_url = "/".join([self.baseurl.rstrip("/"), url.lstrip("/")])
        return self.session.get(full_url)


class AsanaClient(object):
    def __init__(self, access_token):
        asana_config = asana.Configuration()
        asana_config.access_token = access_token
        self.client = asana.ApiClient(asana_config)

    @property
    def tasks(self):
        return asana.TasksApi(self.client)

    @property
    def sections(self):
        return asana.SectionsApi(self.client)


def get_config(ssm_parameter_path):
    """Fetch config values from Parameter Store.

    Args:
        ssm_parameter_path (str): Path to parameters

    Returns:
        configuration (dict): all parameters found at the supplied path.
    """
    configuration = {}
    ssm_client = boto3.client(
        'ssm',
        region_name=environ.get('AWS_DEFAULT_REGION', 'us-east-1'))
    try:
        param_details = ssm_client.get_parameters_by_path(
            Path=ssm_parameter_path,
            Recursive=False,
            WithDecryption=True)

        for param in param_details.get('Parameters', []):
            param_path_array = param.get('Name').split("/")
            section_position = len(param_path_array) - 1
            section_name = param_path_array[section_position]
            configuration[section_name] = param.get('Value')

    except BaseException:
        print("Encountered an error loading config from SSM.")
        traceback.print_exc()
    finally:
        return configuration


def task_data(transaction, project_id, section_id):
    """Formats initial task data."""
    return {
        "completed": False,
        "name": str(transaction['transactionnumber']),
        "projects": [project_id],
        "memberships": [
            {
                "project": project_id,
                "section": section_id
            }
        ]
    }


def get_task_names(asana_tasks, project_gid):
    """Returns a list of task names for all tasks in a project."""
    tasks = asana_tasks.get_tasks_for_project(project_gid, {'limit': 50})
    return list(t['name'] for t in tasks)


def main(event=None, context=None):
    task_count = 0
    full_config_path = f"/{environ.get('ENV')}/{environ.get('APP_CONFIG_PATH')}"
    config = get_config(full_config_path)
    aeon_client = AeonClient(
        config.get("AEON_BASEURL"),
        config.get("AEON_ACCESS_TOKEN"))
    asana_client = AsanaClient(config.get("ASANA_ACCESS_TOKEN"))

    existing_tasks = get_task_names(
        asana_client.tasks, config.get('ASANA_PROJECT_ID'))

    new_transaction_url = f"/odata/Requests?$filter=photoduplicationstatus eq {config.get('AEON_PHOTODUPLICATION_STATUS')} and transactionstatus eq {config.get('AEON_TRANSACTION_STATUS')}"
    transaction_list = aeon_client.get(new_transaction_url).json()
    for transaction in transaction_list['value']:
        lowercase_transaction = {k.lower(): v for k, v in transaction.items()}
        if str(
                lowercase_transaction['transactionnumber']) not in existing_tasks:
            asana_client.tasks.create_task(
                task_data(
                    lowercase_transaction,
                    config.get('ASANA_PROJECT_ID'),
                    config.get('ASANA_UNCLAIMED_SECTION_ID'))
            )
            task_count += 1

    in_billing_url = f"/odata/Requests?$filter=photoduplicationstatus eq {config.get('AEON_BILLING_STATUS')}"
    transaction_list = aeon_client.get(in_billing_url).json()
    for transaction in transaction_list['value']:
        lowercase_transaction = {k.lower(): v for k, v in transaction.items()}
        result = list(
            asana_client.tasks.search_tasks_for_workspace(
                config.get('ASANA_WORKSPACE_ID'),
                {'text': lowercase_transaction['transactionnumber'],
                 'projects.all': config.get('ASANA_PROJECT_ID'),
                 'opt_fields': 'memberships.section'}))
        if len(result) != 1:
            raise Exception(
                f'Expected 1 result for transaction number {lowercase_transaction["transactionnumber"]} but got {len(result)}')
        task = result[0]
        if task['memberships'][0]['section']['gid'] != config.get(
                'ASANA_BILLING_SECTION_ID'):
            asana_client.sections.add_task_for_section(
                config.get('ASANA_BILLING_SECTION_ID'),
                {'body': {'data': {'task': task['gid']}}})

    unit_label = "task" if task_count == 1 else "tasks"
    print(f"{task_count} {unit_label} created")
    return task_count


if __name__ == "__main__":
    main()
