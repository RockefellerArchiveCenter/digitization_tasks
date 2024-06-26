from unittest.mock import call, patch

import boto3
from moto import mock_ssm
from requests import Session

from src.handle_new_digitization_transactions import (AeonClient, get_config,
                                                      main, task_data)


def test_aeon_client():
    baseurl = "https://raccess.rockarch.org/aeon/api"
    access_key = "123456"
    client = AeonClient(baseurl, access_key)
    assert isinstance(client.session, Session)
    assert client.session.headers['User-Agent'] == 'AeonClient/0.1'
    assert client.session.headers['Accept'] == 'application/json'
    assert client.session.headers['X-AEON-API-KEY'] == access_key
    assert client.baseurl == baseurl


def test_task_data():
    """Tests that tasks are structured as expected."""

    transaction_number = 123456
    project_id = 654321
    section_id = 123
    output = task_data({"transactionnumber": transaction_number},
                       project_id, section_id)
    assert output == {
        "completed": False,
        "name": f"{transaction_number}",
        "projects": [project_id],
        "memberships": [
            {
                "project": project_id,
                "section": section_id
            }
        ]
    }


@mock_ssm
def test_config():
    ssm = boto3.client('ssm', region_name='us-east-1')
    path = "/dev/digitization_tasks"
    for name, value in [("foo", "bar"), ("baz", "buzz")]:
        ssm.put_parameter(
            Name=f"{path}/{name}",
            Value=value,
            Type="SecureString",
        )
    config = get_config(path)
    assert config == {'foo': 'bar', 'baz': 'buzz'}


@patch('src.handle_new_digitization_transactions.get_config')
@patch('src.handle_new_digitization_transactions.get_task_names')
@patch('src.handle_new_digitization_transactions.AeonClient.get')
@patch('src.handle_new_digitization_transactions.AsanaClient.tasks')
@patch('src.handle_new_digitization_transactions.AsanaClient.sections')
def test_main(mock_asana_sections, mock_asana_tasks, mock_get_transactions,
              mock_get_task_names, mock_get_config):
    """Test that all methods are called with correct arguments."""
    photoduplication_status = 9
    transaction_status = 22
    billing_status = 21
    project_id = 123456
    unclaimed_section_id = 123
    billing_section_id = 321
    task_id = 987654
    workspace_id = 654321
    mock_get_config.return_value = {
        'AEON_ACCESS_TOKEN': '123456',
        'AEON_BASEURL': 'https://raccess.rockarch.org/aeonapi',
        'AEON_PHOTODUPLICATION_STATUS': photoduplication_status,
        'AEON_TRANSACTION_STATUS': transaction_status,
        'AEON_BILLING_STATUS': billing_status,
        'ASANA_ACCESS_TOKEN': '654321',
        'ASANA_PROJECT_ID': project_id,
        'ASANA_UNCLAIMED_SECTION_ID': unclaimed_section_id,
        'ASANA_BILLING_SECTION_ID': billing_section_id,
        'ASANA_WORKSPACE_ID': workspace_id,
    }
    mock_get_task_names.return_value = ["3", "4"]
    mock_get_transactions.return_value.json.return_value = {
        "value": [
            {"TransactionNumber": 1}, {"transactionNumber": 2}
        ]
    }
    mock_asana_tasks.search_tasks_for_workspace.return_value = [
        {"gid": task_id, "memberships": [{"section": {"gid": unclaimed_section_id}}]}]

    main()

    mock_get_config.assert_called_with('/dev/digitization_tasks')

    assert mock_get_transactions.call_count == 2
    expected_calls = [
        call(
            f'/odata/Requests?$filter=photoduplicationstatus eq {photoduplication_status} and transactionstatus eq {transaction_status}'),
        call().json(),
        call(
            f'/odata/Requests?$filter=photoduplicationstatus eq {billing_status}'),
        call().json()
    ]
    mock_get_transactions.assert_has_calls(expected_calls)

    assert mock_asana_tasks.search_tasks_for_workspace.call_count == 2
    expected_calls = [
        call(workspace_id,
             {'text': 1,
              'opt_fields': 'memberships.section'}),
        call(workspace_id,
             {'text': 2,
              'opt_fields': 'memberships.section'}),
    ]
    mock_asana_tasks.search_tasks_for_workspace.assert_has_calls(
        expected_calls)

    assert mock_asana_tasks.create_task.call_count == 2
    expected_calls = [
        call({'completed': False,
              'name': '1',
              'projects': [project_id],
              'memberships': [{'project': project_id, 'section': unclaimed_section_id}]}),
        call({'completed': False,
              'name': '2',
              'projects': [project_id],
              'memberships': [{'project': project_id, 'section': unclaimed_section_id}]}),
    ]
    mock_asana_tasks.create_task.assert_has_calls(expected_calls)

    assert mock_asana_sections.add_task_for_section.call_count == 2
    mock_asana_sections.add_task_for_section.assert_called_with(
        billing_section_id, {'body': {'data': {'task': task_id}}}
    )

    mock_get_task_names.assert_called_once()
