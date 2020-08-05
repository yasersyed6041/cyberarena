import googleapiclient.discovery
from common.globals import ds_client, dns_suffix, project, dnszone
from googleapiclient.errors import HttpError


# Create a new DNS record for the server and add the information to the datastore for later management
def add_dns_record(build_id, new_ip):
    service = googleapiclient.discovery.build('dns', 'v1')

    # First, get the existing workout DNS
    response = service.resourceRecordSets().list(project=project, managedZone=dnszone,
                                              name=build_id + dns_suffix + ".").execute()
    existing_rrset = response['rrsets']
    change_body = {
        "deletions": existing_rrset,
        "additions": [
            {
                "kind": "dns#resourceRecordSet",
                "name": build_id + dns_suffix + ".",
                "rrdatas": [new_ip],
                "type": "A",
                "ttl": 30
            }
    ]}

    # Try first to perform the DNS change, but in case the DNS did not previously exist, try again without the deletion change.
    try:
        request = service.changes().create(project=project, managedZone=dnszone, body=change_body).execute()
    except HttpError:
        try:
            del change_body["deletions"]
            request = service.changes().create(project=project, managedZone=dnszone, body=change_body).execute()
        except HttpError:
            # Finally, it may be the DNS has already been successfully updated, in which case
            # the API call will throw an error. We ignore this case.
            pass


def delete_dns(build_id, ip_address):
    """
    Deletes a DNS record based on the build_id host name and IP address.
    :param build_id: The Datastore entity build_id, which is also the record host name.
    :param ip_address: The IP address of of the record to delete.
    :return: None
    """
    try:
        service = googleapiclient.discovery.build('dns', 'v1')

        change_body = {"deletions": [
            {
                "kind": "dns#resourceRecordSet",
                "name": build_id + dns_suffix + ".",
                "rrdatas": [ip_address],
                "type": "A",
                "ttl": 30
            }
        ]}

        service.changes().create(project=project, managedZone=dnszone, body=change_body).execute
    except():
        print(f"Error in deleting DNS record for workout {build_id}")
        return False
    return True
