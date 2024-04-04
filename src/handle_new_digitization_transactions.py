#!/usr/bin/env python3

"""Create Asana tasks for every new transaction in Aeon.

Requires encrypted environment variables:
    ENV
    APP_CONFIG_PATH
"""

import traceback
from datetime import datetime
from os import environ

import boto3
from asana import Client
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


def set_last_run_datetime(datetime_str, config_path):
    ssm_client = boto3.client(
        'ssm',
        region_name=environ.get('AWS_DEFAULT_REGION', 'us-east-1'))
    ssm_client.put_parameter(
        Name=f'{config_path}/LAST_RUN_DATETIME',
        Value=datetime_str,
        Type="String",
        Overwrite=True
    )


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
    lowercased = {k.lower(): v for k, v in transaction.items()}
    return {
        "completed": False,
        "name": str(lowercased['transactionnumber']),
        "projects": [project_id],
        "memberships": [
            {
                "project": project_id,
                "section": section_id
            }
        ]
    }


def main(event=None, context=None):
    task_count = 0
    full_config_path = f"/{environ.get('ENV')}/{environ.get('APP_CONFIG_PATH')}"
    config = get_config(full_config_path)
    last_run_datetime = config.get('LAST_RUN_DATETIME')
    aeon_client = AeonClient(
        config.get("AEON_BASEURL"),
        config.get("AEON_ACCESS_TOKEN"))
    asana_client = Client.access_token(config.get("ASANA_ACCESS_TOKEN"))
    # opt-in to deprecation
    asana_client.headers = {
        'asana-enable': 'new_user_task_lists,new_project_templates,new_goal_memberships'}

    new_transaction_url = f"/odata/Requests?$filter=photoduplicationstatus eq {config.get('AEON_STATUS_CODE')} and creationdate gt {last_run_datetime}"
    transaction_list = aeon_client.get(new_transaction_url).json()
    for transaction in transaction_list['value']:
        asana_client.tasks.create_task(
            task_data(
                transaction,
                config.get('ASANA_PROJECT_ID'),
                config.get('ASANA_SECTION_ID'))
        )
        task_count += 1

    label = "task" if task_count == 1 else "tasks"
    print(f"{task_count} {label} created")
    set_last_run_datetime(datetime.now().strftime(
        "%Y-%m-%dT%H:%M:%SZ"), full_config_path)
    return task_count


if __name__ == "__main__":
    main()
