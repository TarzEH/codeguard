import serverConfiguration
import requests
import json
import sys
from pymongo import MongoClient


class DependencyExecutor:
    def __init__(self):
        # Simulation to draw
        self.fetchFromSource = self.getFetcher(
            serverConfiguration.fetchVulnerabilitiesFromNist)

    def getFetcher(self, fetchVulnerabilitiesFromNist):
        if (fetchVulnerabilitiesFromNist):
            return self.fetchVulnerabilitiesFromNist
        return self.fetchVulnerabilitiesFromMongoDB

    def fetchVulnerabilitiesFromNist(self, dependencies):
        try:
            vulnerabilities = []
            for dependency in dependencies["dependencies"]:
                response = requests.get(
                    f'https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch={dependency}')
                if response.status_code == 200:
                    response_body = json.loads(response.text)
                    if (response_body['totalResults'] > 0):
                        vulnerability = {
                            "dependency_name": dependency,
                            "number_of_found_vulnerabilities": len(response_body['vulnerabilities'])
                        }
                        vulnerabilities.append(vulnerability)
                else:
                    print(
                        f'Get Request with parameter Failed with status code {response.status_code}', file=sys.stdout)
            return vulnerabilities
        except Exception as error:
            if serverConfiguration.fetchVulnerabilitiesFromNist:
                raise Exception(
                    f"Failed to fetch vulnerabilities from Nist. err: {error}")
            else:
                print(
                    f'Fallback to Nist failed with: {error}', file=sys.stdout)

    def fetchVulnerabilitiesFromMongoDB(self, dependencies):
        try:
            client = MongoClient(host='mongos', port=27017)
            vulnerabilities = []
            results = []
            for dependency in dependencies["dependencies"]:
                if serverConfiguration.isFakeData:
                    # In fake data mode we dont look at the dependency version
                    parts = dependency.split("==")
                    dependency = parts[0].lower()
                query = {"name": dependency}
                db = client.codegard
                result = db.codegard_cache.find(query)
                for r in result:
                    results.append(r)
                print(result)
                if len(results) > 0:
                    vulnerability = {
                        "dependency_name": dependency,
                        "number_of_found_vulnerabilities": 1,
                        "source": "mongoDB"
                    }
                    vulnerabilities.append(vulnerability)
                elif serverConfiguration.fallBackToNist:
                    nistResult = self.fetchVulnerabilitiesFromNist(
                        {'dependencies': [dependency]})
                    if len(nistResult) > 0:
                        vulnerability = {
                            "dependency_name": dependency,
                            "number_of_found_vulnerabilities": nistResult[0]['number_of_found_vulnerabilities'],
                            "source": "Nist"
                        }
                        vulnerabilities.append(vulnerability)
            return vulnerabilities
        except Exception as error:
            raise Exception(
                f"Failed to fetch vulnerabilities from mongoDB. err: {error}")
