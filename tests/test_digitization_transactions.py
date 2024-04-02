from unittest.mock import call, patch

import boto3
from moto import mock_ssm
from requests import Session

from src.handle_new_digitization_transactions import (AeonClient, get_config,
                                                      main,
                                                      set_last_run_datetime,
                                                      task_data)


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
    output = task_data({"transactionNumber": transaction_number},
                       project_id, section_id)
    assert output == {
        "completed": False,
        "name": transaction_number,
        "projects": [project_id],
        "memberships": [
            {
                "project": project_id,
                "section": section_id
            }
        ]
    }


@mock_ssm
def test_set_last_run_datetime():
    """Tests that LAST_RUN_DATETIME param is set as expected."""
    datetime_str = "2024-01-01T12:00:00Z"
    path = "/dev/digitization_tasks"
    set_last_run_datetime(datetime_str, path)
    config = get_config(path)
    assert config['LAST_RUN_DATETIME'] == datetime_str


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
@patch('asana.client.Client.post')
@patch('src.handle_new_digitization_transactions.set_last_run_datetime')
def test_main(mock_set_datetime, mock_asana_client,
              mock_get_transactions, mock_get_config):
    """Test that all methods are called with correct arguments."""
    status_code = 32
    project_id = 123456
    section_id = 123
    last_run_datetime = "2024-01-01T12:00:00Z"
    mock_get_config.return_value = {
        'AEON_ACCESS_TOKEN': '123456',
        'AEON_BASEURL': 'https://raccess.rockarch.org/aeon/api',
        'AEON_STATUS_CODE': status_code,
        'ASANA_ACCESS_TOKEN': '654321',
        'ASANA_PROJECT_ID': project_id,
        'ASANA_SECTION_ID': section_id,
        'LAST_RUN_DATETIME': last_run_datetime
    }
    mock_get_transactions.return_value.json.return_value = [
        {"transactionNumber": 1}, {"transactionNumber": 2}]

    main()

    mock_get_config.assert_called_with('/dev/digitization_tasks')
    mock_get_transactions.assert_called_once_with(
        f'/odata/Requests?$filter=transactionstatus eq {status_code} and creationddate gt {last_run_datetime}')
    assert mock_asana_client.call_count == 2
    expected_calls = [
        call('/tasks',
             {'completed': False,
              'name': 1,
              'projects': [project_id],
              'memberships': [{'project': project_id,
                               'section': section_id}]}),
        call('/tasks',
             {'completed': False,
              'name': 2,
              'projects': [project_id],
              'memberships': [{'project': project_id,
                               'section': section_id}]})
    ]
    mock_asana_client.assert_has_calls(expected_calls)
    mock_set_datetime.assert_called_once()
