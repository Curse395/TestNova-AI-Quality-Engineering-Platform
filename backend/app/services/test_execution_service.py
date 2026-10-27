
import ipaddress
import socket
import time
import httpx
import os 
from typing import Any
from urllib.parse import urlsplit
from sqlalchemy.orm import Session
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_execution import TestExecutionRun
from app.schemas.test_execution_schema import APIRequestConfig


class TestExecutionService:
    """Execute explicitly configured API checks for approved test cases."""

    def __init__(self, db: Session):
        self.db = db

    def _presist_execution(self,user_id:int,project_id:int,test_case_id:int,result:dict[str,Any],config:APIRequestConfig)->None:
        """Presist an execution result without storing request credentials"""

        try:
            run=TestExecutionRun(
                project_id=project_id,
                test_case_id=test_case_id,
                executed_by_user_id=user_id,
                execution_type=result["execution_type"],
                status=result["status"],
                http_status_code=result["http_status_code"],
                duration_ms=result["duration_ms"],
                assertions=result["assertions"],
                error=result["error"],
                request_snapshot=self._build_request_snapshot(config),
                expected_status_code=config.expected_status_code,
                expected_json_fields=config.expected_json_fields
            )

            self.db.add(run)
            self.db.commit()
            self.db.refresh(run)

            result["execution_run_id"]=run.id
            result["history_saved"]=True

        except Exception as exc:
            self.db.rollback()
            print(f"[Execution history save error: {exc!r}]")
            result["history_saved"]=False
            result["history_error"]=("Execution completed, but its history could not be saved")

    def _verify_project_access(
        self,
        user_id: int,
        project_id: int,
        test_case_id: int,
    ) -> TestCase:
        project = (self.db.query(Project).join(Organization).filter(Project.id == project_id,Organization.owner_id == user_id).first())

        if project is None:
            raise ValueError("Project not found or access denied.")

        test_case = (self.db.query(TestCase).filter(TestCase.id == test_case_id,TestCase.project_id == project_id).first())

        if test_case is None:
            raise ValueError("Test case not found in this project.")

        if test_case.review_status != "approved":
            raise ValueError(
                "Only approved test cases can be executed."
            )

        return test_case

    @staticmethod
    def _validate_target(url: str) -> None:
        """Validate HTTPS targets against an explicit host allowlist."""
        from urllib.parse import urlsplit

        parsed = urlsplit(url)

        if parsed.scheme.lower() != "https":
            raise ValueError("Only HTTPS API targets are allowed.")

        if not parsed.hostname:
            raise ValueError("The API target must have a hostname.")

        if parsed.username or parsed.password:
            raise ValueError("Credentials in URLs are not allowed.")

        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Invalid target port.") from exc

        if port not in (None, 443):
            raise ValueError("Only the standard HTTPS port is allowed.")

        hostname = parsed.hostname.rstrip(".").lower()

        allowed_hosts = {
            host.strip().rstrip(".").lower()
            for host in os.getenv("TEST_EXECUTION_ALLOWED_HOSTS", "").split(",")
            
            if host.strip()
        }

        if not allowed_hosts:
            raise ValueError("API execution is disabled: no allowed hosts configured.")

        if hostname not in allowed_hosts:
            raise ValueError(f"API target '{hostname}' is not in the allowed host list.")

        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None

        if address is not None:
            if not address.is_global:
                raise ValueError("Private or reserved IP targets are not allowed.")
            return

        try:
            resolved = socket.getaddrinfo(
                hostname,
                443,
                type=socket.SOCK_STREAM)
            
        except socket.gaierror as exc:
            raise ValueError("API target hostname could not be resolved.") from exc

        if not resolved:
            raise ValueError("API target hostname could not be resolved.")

        for item in resolved:
            resolved_ip = ipaddress.ip_address(item[4][0])

            if not resolved_ip.is_global:
                raise ValueError("API target resolves to a private or reserved address.")
            
    @staticmethod
    def _check_json_fields(
        response_data: Any,
        expected_fields: dict[str, Any],
    ) -> list[dict[str, Any]]:
        failures = []

        for field_path, expected_value in expected_fields.items():
            current = response_data

            for part in field_path.split("."):
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    current = object()
                    break

            if current != expected_value:
                failures.append(
                    {
                        "check": f"json_field:{field_path}",
                        "expected": expected_value,
                        "actual": (None if type(current) is object else current)
                    }
                )

        return failures

    
    @staticmethod
    def _build_request_snapshot(config: APIRequestConfig) -> dict[str, Any]:
        """Capture request configuration without storing sensitive headers."""

        sensitive_headers = {
            "authorization",
            "proxy-authorization",
            "cookie",
            "set-cookie",
            "x-api-key",
            "api-key"
        }

        safe_headers = {key: value for key, value in config.headers.items() if key.lower() not in sensitive_headers}

        return {
            "method": config.method,
            "url": str(config.url),
            "headers": safe_headers,
            "params": config.params,
            "json_body": config.json_body,
            "timeout_seconds": config.timeout_seconds
        }


    def execute_api_test(
        self,
        user_id: int,
        project_id: int,
        test_case_id: int,
        config: APIRequestConfig,
    ) -> dict[str, Any]:

        print("EXECUTE_API_TEST CALLED", project_id, test_case_id)
        test_case = self._verify_project_access(
            user_id=user_id,
            project_id=project_id,
            test_case_id=test_case_id )

        target_url = str(config.url)
        self._validate_target(target_url)

        started = time.perf_counter()

        result: dict[str, Any] = {
            "success": True,
            "project_id": project_id,
            "test_case_id": test_case.id,
            "test_case_title": test_case.title,
            "execution_type": "api",
            "status": "error",
            "http_status_code": None,
            "duration_ms": None,
            "assertions": [],
            "error": None,
            "note": (
                "This execution uses the explicitly supplied request "
                "configuration. It does not infer executable actions "
                "from natural-language test steps."
            ),
        }

        try:
            with httpx.Client(
                timeout=config.timeout_seconds,
                follow_redirects=False,
                trust_env=False
            ) as client:
                response = client.request(
                    method=config.method,
                    url=target_url,
                    headers=config.headers,
                    params=config.params,
                    json=config.json_body
                )

            result["http_status_code"] = response.status_code

            status_passed = (response.status_code == config.expected_status_code)

            result["assertions"].append(
                {
                    "check": "status_code",
                    "passed": status_passed,
                    "expected": config.expected_status_code,
                    "actual": response.status_code
                }
            )

            response_data = None

            if config.expected_json_fields:
                try:
                    response_data = response.json()
                    field_failures = self._check_json_fields(response_data,config.expected_json_fields)
                    checked_fields = len(config.expected_json_fields)

                    result["assertions"].append(
                        {
                            "check": "json_fields",
                            "passed": not field_failures,
                            "checked": checked_fields,
                            "failures": field_failures
                        }
                    )

                except ValueError:
                    result["assertions"].append(
                        {
                            "check": "json_fields",
                            "passed": False,
                            "error": "Response body was not valid JSON."
                        }
                    )

            all_passed = all(assertion.get("passed", False) for assertion in result["assertions"])

            result["status"] = "passed" if all_passed else "failed"

        except httpx.TimeoutException:
            result["status"] = "error"
            result["error"] = "API request timed out."

        except httpx.RequestError as exc:
            result["status"] = "error"
            result["error"] = (f"API request failed: {type(exc).__name__}")

        finally:
            result["duration_ms"] = round((time.perf_counter() - started) * 1000,2)

        self._presist_execution(
            user_id=user_id,
            project_id=project_id,
            test_case_id=test_case_id,
            result=result,
            config=config
        )

        return result

    def get_execution_history(self,user_id:int,project_id:int,limit:int=20,offset:int=0)->dict[str,Any]:
        """return paginated execution history for an owned project"""

        project=(self.db.query(Project).join(Organization).filter(Project.id==project_id,Organization.owner_id==user_id).first())

        if project is None:
            raise ValueError("Project could not be found or access deined")

        query=self.db.query(TestExecutionRun).filter(TestExecutionRun.project_id==project_id)
        total=query.count()
        runs=(query.order_by(TestExecutionRun.created_at.desc(),TestExecutionRun.id.desc()).offset(offset).limit(limit).all())

        return {
            "success": True,
            "project_id": project_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "executions": [
                {
                    "id": run.id,
                    "test_case_id": run.test_case_id,
                    "executed_by_user_id": run.executed_by_user_id,
                    "execution_type": run.execution_type,
                    "status": run.status,
                    "http_status_code": run.http_status_code,
                    "duration_ms": run.duration_ms,
                    "assertions": run.assertions,
                    "error": run.error,
                    "created_at": run.created_at,
                }for run in runs
            ]
        }       

    
    def get_execution_details(
        self,
        user_id: int,
        project_id: int,
        run_id: int,
    ) -> dict[str, Any]:
        """Return detailed execution data with its test case and evidence."""

        project = (self.db.query(Project).join(Organization).filter(Project.id == project_id,Organization.owner_id == user_id).first())
    
        if project is None:
            raise ValueError("Project not found or access denied.")

        run = (self.db.query(TestExecutionRun).filter(TestExecutionRun.id == run_id,TestExecutionRun.project_id == project_id).first())

        if run is None:
            raise ValueError("Execution run not found in this project.")

        test_case = (self.db.query(TestCase).filter(TestCase.id == run.test_case_id,TestCase.project_id == project_id).first())

        if test_case is None:
            raise ValueError("Associated test case not found.")

        evidence = [
            {
                "evidence_id": item.id,
                "document_id": item.document_id,
                "chunk_id": item.chunk_id
            }
            for item in test_case.evidence
        ]

        return {
            "success": True,
            "project_id": project_id,
            "execution": {
                "id": run.id,
                "test_case_id": run.test_case_id,
                "executed_by_user_id": run.executed_by_user_id,
                "execution_type": run.execution_type,
                "status": run.status,
                "http_status_code": run.http_status_code,
                "duration_ms": run.duration_ms,
                "assertions": run.assertions,
                "error": run.error,
                "created_at": run.created_at,
                "request_snapshot": run.request_snapshot,
                "expected_status_code": run.expected_status_code,
                "expected_json_fields": run.expected_json_fields
            },
            "test_case": {
                "id": test_case.id,
                "title": test_case.title,
                "description": test_case.description,
                "category": test_case.category,
                "priority": test_case.priority,
                "preconditions": test_case.preconditions,
                "steps": test_case.steps,
                "expected_result": test_case.expected_result,
                "review_status": test_case.review_status
            },
            "evidence": evidence
        }



