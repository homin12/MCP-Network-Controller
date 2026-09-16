import os
import tempfile
import asyncio
from typing import Dict, List, Any, Optional
from loguru import logger

from pybatfish.client.session import Session
from pybatfish import question as bfq
from pybatfish.exception import BatfishException

class BatfishClientError(Exception):
    """Исключение для ошибок Batfish"""
    pass


class BatfishClientWrapper:
    """
    Валидатор конфигураций на базе Batfish.
    Пре-валидация команд до их применения в сети.
    """
    
    def __init__(self, host: str = "batfish", 
                 network_name: str = "telecom_networks", 
                 retry_count: int = 3):
        self.host = host
        self.network_name = network_name
        self.retry_count = retry_count
        self._session: Optional[Session] = None
        self._connected = False

    async def connect(self) -> "BatfishClientWrapper":     
        for attempt in range(self.retry_count):
            try:
                self._session = Session(host="batfish")
                
                await asyncio.to_thread(self._session.set_network, self.network_name)
                
                logger.info("Synchronizing plugins with the Batfish server")
                await asyncio.to_thread(lambda: dir(self._session.q))
                
                self._connected = True
                logger.info(f"Successful connection to the Batfish ({self.host})")
                return self
                
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1}/{self.retry_count} failed: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(2)
                else:
                    logger.error(f"Oops, failed to connect to the Batfish server: {e}")
                    raise BatfishClientError(f"failed to connect to the Batfish server: {e}")

    
    async def init_snapshot(self, snapshot_name: str, device_configs: Dict[str, str]) -> bool:
        """
        Создает снимок сети внутри Batfish.
        """
        if not self._connected or not self._session:
            raise BatfishClientError("Валидатор Batfish не подключен к сети")        
        
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                configs_dir = os.path.join(tmp_dir, "configs")
                os.makedirs(configs_dir, exist_ok=True)
                
                for device_name, config_text in device_configs.items():
                    file_path = os.path.join(configs_dir, f"{device_name}.cfg")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(config_text)
                
                await asyncio.to_thread(
                    self._session.init_snapshot, 
                    upload=tmp_dir, 
                    name=snapshot_name, 
                    overwrite=True
                )
                
            logger.info(f"Digital twin snapshot '{snapshot_name}' successfully deployed.")
            return True
            
        except Exception as e:
            logger.error(f"Network snapshot compilation error in Batfish.: {e}")
            raise BatfishClientError(f"Ошибка компиляции снимка сети в Batfish: {e}")
    
    async def _run_question(self, question, timeout: int = 30) -> List[Dict[str, Any]]:
        try:
            answer = await asyncio.wait_for(
                asyncio.to_thread(question.answer),
                timeout=timeout
            )

            df = answer.frame()
            return df.to_dict(orient="records")
            
        except asyncio.TimeoutError:
            logger.warning("Batfish query execution timeout")
            return []
        except Exception as e:
            logger.warning(f"Error executing query: {e}")
            return []
            
    async def validate_config_syntax(self, snapshot_name: str) -> Dict[str, Any]:      
        try:
            await asyncio.to_thread(self._session.set_snapshot, snapshot_name)
            
            parse_status_data = await self._run_question(self._session.q.fileParseStatus())
            init_issues_data = await self._run_question(self._session.q.initIssues())
            
            parse_list = parse_status_data if isinstance(parse_status_data, list) else []
            issues_list = init_issues_data if isinstance(init_issues_data, list) else []
            
            syntax_errors = []
            
            # Собираем падения парсера из fileParseStatus.
            for file in parse_list:
                status = str(file.get("Status", "")).upper()
                if status == "FAILED":
                    nodes = file.get("Nodes")
                    device_name = nodes[0] if isinstance(nodes, list) and nodes else "Unknown Device"
                    
                    syntax_errors.append({
                        "device": device_name,
                        "message": f"Критическая ошибка: файл {file.get('File_Name')} полностью не распознан парсером.",
                        "severity": "error"
                    })
            
            # Собираем синтаксические предупреждения из initIssues.
            for issue in issues_list:
                severity = str(issue.get("Severity", "")).upper()
                issue_type = str(issue.get("Type", "")).upper()
                
                # Фильтруем только критические ошибки синтаксиса.
                if severity == "ERROR" or "PARSE" in issue_type or "REDFLAG" in severity:
                    nodes = issue.get("Nodes")
                    device_name = nodes[0] if isinstance(nodes, list) and nodes else "Unknown Device"
                    
                    syntax_errors.append({
                        "device": device_name,
                        "message": issue.get("Details", "Нераспознанная или ошибочная команда в конфигурации"),
                        "severity": "error" if severity == "ERROR" else "warning"
                    })
            logger.warning(f"validate_config_syntax failed: {syntax_errors}, {len([e for e in syntax_errors if e['severity'] == 'error']) == 0}")

            return {
                "syntax_errors": syntax_errors,
                "passed": len([e for e in syntax_errors if e["severity"] == "error"]) == 0
            }
        except Exception as e:
            logger.warning(f"validate_config_syntax error: {e}")
            return {"syntax_errors": [], "error": str(e), "passed": False}


    async def validate_routing(self, snapshot_name: str) -> Dict[str, Any]:       
        try:
            await asyncio.to_thread(self._session.set_snapshot, snapshot_name)
            
            bgp_data = await self._run_question(self._session.q.bgpProcessConfiguration())
            ospf_data = await self._run_question(self._session.q.ospfProcessConfiguration())
            routes_data = await self._run_question(self._session.q.routes())
            
            bgp_list = bgp_data if isinstance(bgp_data, list) else []
            ospf_list = ospf_data if isinstance(ospf_data, list) else []
            routes_list = routes_data if isinstance(routes_data, list) else []
            
            return {
                "bgp": {
                    "configured_nodes": len(bgp_list),
                    "issues": [b for b in bgp_list if b.get("Status") == "unrecognized"]
                },
                "ospf": {
                    "configured_areas": len(ospf_list),
                    "processes": ospf_list
                },
                "routes": {
                    "total_computed_routes": len(routes_list)
                }
            }
        except Exception as e:
            logger.error(f"Routing validation error: {e}")
            return {"error": str(e)}


    async def validate_compliance(self, snapshot_name: str, rules: List[str]) -> Dict[str, Any]:
        results = {"passed": True, "violations": [], "rules_checked": []}
        
        for rule in rules:
            if "acl" in rule.lower():
                results["rules_checked"].append("ACL_Reachability")
                try:
                    acl_data = await self._run_question(self._session.q.filterLineReachability())
                    
                    acl_list = acl_data if isinstance(acl_data, list) else []
                    
                    blocked_rules = [a for a in acl_list if "unreachable" in str(a.get("Action", "")).lower() or a.get("Action") == "BLOCKED"]
                    
                    if blocked_rules:
                        results["passed"] = False
                        for br in blocked_rules:
                            results["violations"].append({
                                "rule": "ACL_Reachability",
                                "details": (
                                    f"Узел {br.get('Node')}: В ACL '{br.get('Filter_Name', br.get('Acl'))}' "
                                    f"строка №{br.get('Line_Index')} является недостижимой. "
                                    f"Причина: {br.get('Reason', 'Перекрывается другими правилами')}"
                                )
                            })
                        logger.warning(f"validate_compliance failed: {blocked_rules}")
                except Exception as e:
                    logger.warning(f"Упс, validate_compliance error: {e}")
                    results["violations"].append({"rule": "ACL_Reachability", "details": str(e)})
                    
        return results
