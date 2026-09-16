import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger

from models import (
    ValidationResult, 
    ValidationIssue, 
    ValidationSeverity, 
    ValidationStatus
)
from .batfish_client import BatfishClientWrapper, BatfishClientError


class ValidationService:
    """
    Сервис проверок цифрового двойника сети Batfish.
    """
    def __init__(self, batfish_host: str = "http://batfish:9996/v2",
                 network_name: str = "telecom_networks",
                 batfish_enabled: bool = True):
        self.batfish_host = batfish_host
        self.network_name = network_name
        self.batfish_enabled = batfish_enabled
        self.batfish_client: Optional[BatfishClientWrapper] = None
    
    async def initialize(self):
        if not self.batfish_enabled:
            return
        
        try:
            self.batfish_client = BatfishClientWrapper(
                host=self.batfish_host,
                network_name=self.network_name
            )
            await self.batfish_client.connect()
        except Exception as e:
            logger.error(f"Failed to activate the Batfish service: {e}")
            logger.warning("Batfish is disabled. The agent will continue operation without syntactic analysis.")
            self.batfish_enabled = False

    
    async def validate_configurations(self, 
                                      device_configs: Dict[str, str],
                                      project_id: str,
                                      check_types: List[str] = None) -> ValidationResult:
        if not self.batfish_enabled:
            return self._create_skipped_result(project_id)
        
        if not device_configs:
            return self._create_empty_result(project_id)
                
        check_types = check_types or ["syntax", "routing"]
        start_time = time.time()
        issues = []
        
        try:
            snapshot_name = f"val_{project_id}_{int(time.time())}"
            
            # Разворачиваем снимок конфигураций в Batfish.
            await self.batfish_client.init_snapshot(snapshot_name, device_configs)
            
            if "syntax" in check_types:
                syntax_result = await self.batfish_client.validate_config_syntax(snapshot_name)
                issues.extend(self._convert_batfish_issues(syntax_result, "syntax"))
            
            if "routing" in check_types:
                routing_result = await self.batfish_client.validate_routing(snapshot_name)
                issues.extend(self._convert_routing_issues(routing_result))
            
            if "compliance" in check_types:
                compliance_result = await self.batfish_client.validate_compliance(
                    snapshot_name,
                    ["acl", "ospf", "bgp", "security"]
                )
                issues.extend(self._convert_compliance_issues(compliance_result))
            
        except BatfishClientError as e:
            logger.error(f"Batfish infrastructure error: {e}")
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                message=f"Batfish ошибка: {e}",
                suggestion="Проверьте доступность и статус Batfish"
            ))
        except Exception as e:
            logger.error(f"Unexpected exception during network simulation: {e}")
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                message=f"Внутренний сбой анализатора: {e}",
                suggestion="Проверьте корректность формата файлов конфигурации"
            ))

        logger.warning(f"Batfish errors: {issues}")
        duration_ms = (time.time() - start_time) * 1000
        return self._build_result(issues, project_id, duration_ms)

    
    def _convert_batfish_issues(self, result: Dict[str, Any], 
                                check_type: str) -> List[ValidationIssue]:
        issues = []
        syntax_errors = result.get("syntax_errors", [])
        
        for error in syntax_errors:
            dev = error.get("device")
            dev_str = ", ".join(dev) if isinstance(dev, list) else str(dev)
            msg = error.get("message", "")
            
            severity_level = ValidationSeverity.ERROR
            if "syntax is unrecognized" in msg.lower():
                severity_level = ValidationSeverity.WARNING
                
            issues.append(ValidationIssue(
                severity=severity_level,
                message=msg,
                device=dev_str,
                suggestion="Проверьте правильность написания CLI команд или контекст их выполнения (конфигурационный режим)",
                rule_name=f"syntax_{check_type}"
            ))
        return issues

    
    def _convert_routing_issues(self, result: Dict[str, Any]) -> List[ValidationIssue]:
        issues = []
        
        bgp = result.get("bgp", {})
        bgp_issues = bgp.get("issues", [])
        for issue in bgp_issues:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                message=f"BGP: Нераспознанная или аномальная конфигурация пиринга на узле {issue.get('Node')}",
                device=issue.get("Node"),
                rule_name="routing_bgp"
            ))
            
        ospf = result.get("ospf", {})
        if ospf and ospf.get("configured_areas") == 0:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.INFO,
                message="OSPF: На узлах объявлены команды OSPF, но логические зоны (areas) не скомпилированы.",
                rule_name="routing_ospf"
            ))
        
        if "error" in result:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                message=result["error"],
                rule_name="routing_general"
            ))
        logger.warning(f"_convert_routing_issues errors: {issues}")
        return issues
    
    def _convert_compliance_issues(self, result: Dict[str, Any]) -> List[ValidationIssue]:
        issues = []
        violations = result.get("violations", [])
        for violation in violations:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                message=f"Нарушение политики безопасности: {violation.get('details', '')}",
                rule_name=violation.get("rule", "security_compliance")
            ))
        logger.warning(f"_convert_compliance_issues errors: {issues}")
        return issues
    
    def _build_result(self, issues: List[ValidationIssue], 
                      project_id: str, 
                      duration_ms: float) -> ValidationResult:
        summary = {"info": 0, "warning": 0, "error": 0, "critical": 0}
        
        for issue in issues:
            severity = issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity)
            if severity in summary:
                summary[severity] += 1
        
        # Сеть считается прошедшей тест, если нет критических ошибок и нарушений безопасности.
        passed = summary["critical"] == 0 and summary["error"] == 0
        logger.warning(f"Прошло ли : {passed}")
        return ValidationResult(
            status=ValidationStatus.SUCCESS,
            issues=issues,
            summary=summary,
            passed=passed,
            timestamp=datetime.now().isoformat(),
            duration_ms=duration_ms
        )
    
    def _create_skipped_result(self, project_id: str) -> ValidationResult:
        return ValidationResult(
            status=ValidationStatus.SUCCESS,
            issues=[],
            summary={"info": 0, "warning": 0, "error": 0, "critical": 0},
            passed=True,
            timestamp=datetime.now().isoformat(),
            duration_ms=0
        )
    
    def _create_empty_result(self, project_id: str) -> ValidationResult:
        return ValidationResult(
            status=ValidationStatus.SUCCESS,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    message="Пул сгенерированных конфигураций пуст. Валидация не требуется."
                )
            ],
            summary={"info": 1, "warning": 0, "error": 0, "critical": 0},
            passed=True,
            timestamp=datetime.now().isoformat(),
            duration_ms=0
        )
