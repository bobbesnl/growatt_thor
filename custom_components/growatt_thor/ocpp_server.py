"""OCPP Server implementation for Growatt THOR."""
import logging
from typing import Optional, Any, Dict, List
from datetime import datetime

_LOGGER = logging.getLogger(__name__)


class OCPPServer:
    """OCPP server handler for Growatt THOR charger."""

    def __init__(self, coordinator: Any) -> None:
        """Initialize OCPP server.
        
        Args:
            coordinator: GrowattCoordinator instance for data updates
        """
        self.coordinator = coordinator
        self._logger = _LOGGER

    async def handle_authorize(self, id_tag: str) -> bool:
        """Handle Authorize request from charger.
        
        Args:
            id_tag: RFID or card identifier
            
        Returns:
            True if authorized, False otherwise
        """
        try:
            _LOGGER.info("Authorization request for tag: %s", id_tag)
            # TODO: Implement proper authorization logic
            return True
        except Exception as exc:
            _LOGGER.error("Authorization failed: %s", exc, exc_info=True)
            return False

    async def handle_start_transaction(self, 
                                      connector_id: int,
                                      id_tag: str,
                                      meter_start: int,
                                      timestamp: str) -> int:
        """Handle StartTransaction request.
        
        Args:
            connector_id: Connector identifier
            id_tag: RFID/card tag
            meter_start: Starting meter reading (Wh)
            timestamp: Transaction start time (ISO 8601)
            
        Returns:
            Transaction ID
        """
        try:
            transaction_id = int(datetime.now().timestamp() * 1000)
            _LOGGER.info(
                "Transaction started: id=%d, tag=%s, meter=%d",
                transaction_id, id_tag, meter_start
            )
            self.coordinator.start_transaction(transaction_id, id_tag)
            return transaction_id
        except Exception as exc:
            _LOGGER.error("Failed to start transaction: %s", exc, exc_info=True)
            raise

    async def handle_stop_transaction(self,
                                     transaction_id: int,
                                     meter_stop: int,
                                     timestamp: str,
                                     reason: Optional[str] = None) -> bool:
        """Handle StopTransaction request.
        
        Args:
            transaction_id: Transaction ID to stop
            meter_stop: Ending meter reading (Wh)
            timestamp: Stop time (ISO 8601)
            reason: Reason for stopping
            
        Returns:
            True if successful
        """
        try:
            energy = meter_stop / 1000.0  # Convert Wh to kWh
            _LOGGER.info(
                "Transaction stopped: id=%d, energy=%.3f kWh, reason=%s",
                transaction_id, energy, reason
            )
            self.coordinator.stop_transaction(reason)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to stop transaction: %s", exc, exc_info=True)
            return False

    async def handle_meter_values(self, 
                                 transaction_id: Optional[int],
                                 meter_values: List[Dict[str, Any]]) -> bool:
        """Handle MeterValues request.
        
        Args:
            transaction_id: Transaction ID (if during charging)
            meter_values: List of meter values
            
        Returns:
            True if processed successfully
        """
        try:
            if not meter_values:
                _LOGGER.debug("Received empty meter values")
                return True
                
            _LOGGER.debug("Processing %d meter value entries", len(meter_values))
            self.coordinator.process_meter_values(meter_values)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to process meter values: %s", exc, exc_info=True)
            return False

    async def handle_status_notification(self,
                                        connector_id: int,
                                        status: str,
                                        error_code: str = "NoError",
                                        timestamp: Optional[str] = None) -> bool:
        """Handle StatusNotification request.
        
        Args:
            connector_id: Connector identifier
            status: Charger status (Idle, Charging, Faulted, etc.)
            error_code: Error code if any
            timestamp: Status time
            
        Returns:
            True if processed successfully
        """
        try:
            _LOGGER.info("Status: %s (error=%s)", status, error_code)
            self.coordinator.set_status(status)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to handle status notification: %s", exc, exc_info=True)
            return False

    async def handle_data_transfer(self, 
                                  vendor_id: str,
                                  message_id: Optional[str],
                                  data: Dict[str, Any]) -> bool:
        """Handle DataTransfer request (custom Growatt data).
        
        Args:
            vendor_id: Vendor identifier (Growatt)
            message_id: Message type identifier
            data: Custom data payload
            
        Returns:
            True if processed successfully
        """
        try:
            _LOGGER.debug("DataTransfer from %s: %s", vendor_id, message_id)
            
            if message_id == "GetMeterValues":
                if "MeterValues" in data:
                    await self.handle_meter_values(None, data["MeterValues"])
                    
            elif message_id == "GetConfiguration":
                if "ConfigurationKey" in data:
                    self.coordinator.process_configuration(data["ConfigurationKey"])
                    
            elif message_id == "frozenrecord":
                self.coordinator.process_frozen_record(data)
                
            return True
        except Exception as exc:
            _LOGGER.error("Failed to handle DataTransfer: %s", exc, exc_info=True)
            return False

    async def handle_get_configuration(self,
                                      configuration_key: Optional[List[str]] = None) -> Dict[str, Any]:
        """Handle GetConfiguration request.
        
        Args:
            configuration_key: Specific keys to retrieve, or None for all
            
        Returns:
            Configuration dictionary
        """
        try:
            _LOGGER.debug("GetConfiguration request: keys=%s", configuration_key)
            # TODO: Implement proper configuration retrieval
            return {"ConfigurationKey": []}
        except Exception as exc:
            _LOGGER.error("Failed to get configuration: %s", exc, exc_info=True)
            raise

    async def handle_change_configuration(self,
                                         key: str,
                                         value: str) -> bool:
        """Handle ChangeConfiguration request.
        
        Args:
            key: Configuration key to change
            value: New value
            
        Returns:
            True if change accepted
        """
        try:
            _LOGGER.info("ChangeConfiguration: %s = %s", key, value)
            # TODO: Implement proper configuration change handling
            return True
        except Exception as exc:
            _LOGGER.error("Failed to change configuration: %s", exc, exc_info=True)
            return False

    async def handle_remote_start(self, transaction_id: int, id_tag: str) -> bool:
        """Handle RemoteStartTransaction request.
        
        Args:
            transaction_id: Transaction ID
            id_tag: RFID/card tag
            
        Returns:
            True if accepted
        """
        try:
            _LOGGER.info("Remote start requested: %s", id_tag)
            self.coordinator.start_transaction(transaction_id, id_tag)
            return True
        except Exception as exc:
            _LOGGER.error("Failed to handle remote start: %s", exc, exc_info=True)
            return False

    async def handle_remote_stop(self, transaction_id: int) -> bool:
        """Handle RemoteStopTransaction request.
        
        Args:
            transaction_id: Transaction ID to stop
            
        Returns:
            True if accepted
        """
        try:
            _LOGGER.info("Remote stop requested: %d", transaction_id)
            self.coordinator.stop_transaction("Remote")
            return True
        except Exception as exc:
            _LOGGER.error("Failed to handle remote stop: %s", exc, exc_info=True)
            return False
