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
    location = "106.1.1"
    output = task_data(
        {
            "transactionnumber": transaction_number,
            "creationdate": "2010-01-01T00:00:00.000Z",
            "location": location
        },
        project_id, section_id)
    assert output == {
        "data":
        {
            "completed": False,
            "due_on": "2010-04-01",
            "name": f"{transaction_number}",
            "projects": [project_id],
            "notes": location,
            "memberships": [
                {
                    "project": project_id,
                    "section": section_id
                }
            ]
        }
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
@patch('src.handle_new_digitization_transactions.AeonClient.get')
@patch('src.handle_new_digitization_transactions.AsanaClient.tasks')
def test_main(mock_asana_tasks, mock_get_transactions, mock_get_config):
    """Test that all methods are called with correct arguments."""
    photoduplication_status = 9
    transaction_status = 22
    cancelled_staff_status = 25
    cancelled_user_status = 26
    project_id = 123456
    unclaimed_section_id = 123
    workspace_id = 654321
    location = "106.1.1"
    mock_get_config.return_value = {
        'AEON_ACCESS_TOKEN': '123456',
        'AEON_BASEURL': 'https://raccess.rockarch.org/aeonapi',
        'AEON_PHOTODUPLICATION_STATUS': photoduplication_status,
        'AEON_TRANSACTION_STATUS': transaction_status,
        'AEON_CANCELLED_STAFF_STATUS': cancelled_staff_status,
        'AEON_CANCELLED_USER_STATUS': cancelled_user_status,
        'ASANA_ACCESS_TOKEN': '654321',
        'ASANA_PROJECT_ID': project_id,
        'ASANA_UNCLAIMED_SECTION_ID': unclaimed_section_id,
        'ASANA_WORKSPACE_ID': workspace_id,
    }
    mock_get_transactions.return_value.json.side_effect = [
        {
            "value": [
                {
                    "TransactionNumber": 1,
                    "creationDate": "2010-01-01T00:00:00.000Z",
                    "location": location
                },
                {
                    "transactionNumber": 2,
                    "creationdate": "2010-01-01T00:00:00.000Z",
                    "location": location
                }
            ]
        },
        {"transactionNumber": 5, "photoduplicationStatus": 25},
        {"transactionnumber": 6, "photoduplicationstatus": 26}
    ]
    mock_asana_tasks.get_tasks_for_project.return_value = [
        {"name": "5", "gid": "123456"}, {"name": "6", "gid": "654321"}
    ]

    main()

    mock_get_config.assert_called_with('/dev/digitization_tasks')

    assert mock_get_transactions.call_count == 3
    expected_calls = [
        call(
            f'/odata/Requests?$filter=photoduplicationstatus eq {photoduplication_status} and transactionstatus eq {transaction_status}'),
        call().json(),
        call('/Requests/5'),
        call().json(),
        call('/Requests/6'),
        call().json()
    ]
    mock_get_transactions.assert_has_calls(expected_calls)

    assert mock_asana_tasks.create_task.call_count == 2
    expected_calls = [
        call({'data':
              {'completed': False,
               'due_on': '2010-04-01',
               'notes': location,
               'name': '1',
               'projects': [project_id],
               'memberships': [{'project': project_id, 'section': unclaimed_section_id}]}}, {}),
        call({'data':
              {'completed': False,
               'due_on': '2010-04-01',
               'notes': location,
               'name': '2',
               'projects': [project_id],
               'memberships': [{'project': project_id, 'section': unclaimed_section_id}]}}, {}),
    ]
    mock_asana_tasks.create_task.assert_has_calls(expected_calls)

    assert mock_asana_tasks.update_task.call_count == 2
    expected_calls = [
        call({'data': {'completed': True, 'notes': 'Cancelled by staff.'}}, '123456', {}),
        call({'data': {'completed': True, 'notes': 'Cancelled by user.'}}, '654321', {})
    ]
    mock_asana_tasks.update_task.assert_has_calls(expected_calls)
