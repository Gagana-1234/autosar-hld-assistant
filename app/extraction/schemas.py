"""
app/extraction/schemas.py
Pydantic models for AUTOSAR entity types extracted from HLD documents.
These schemas define the structured data captured for each entity kind.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SWComponent(BaseModel):
    """Software Component extracted from HLD document."""
    name: str = Field(..., description="SWC name, e.g. 'EngineControlSWC'")
    swc_type: str = Field(
        default="ApplicationSwComponentType",
        description="AUTOSAR SWC type classification",
    )
    description: str = Field(default="", description="Brief description of the SWC")
    ports: list[str] = Field(default_factory=list, description="Port names (R-port, P-port)")
    runnables: list[str] = Field(default_factory=list, description="Runnable entity names")
    layer: str = Field(default="", description="AUTOSAR layer: Application, RTE, BSW, etc.")


class Interface(BaseModel):
    """AUTOSAR interface (sender-receiver or client-server)."""
    name: str = Field(..., description="Interface name")
    interface_type: str = Field(
        default="SenderReceiverInterface",
        description="One of: SenderReceiverInterface, ClientServerInterface",
    )
    data_elements: list[str] = Field(default_factory=list, description="Data element names")
    operations: list[str] = Field(default_factory=list, description="Operation names (for CS interfaces)")
    description: str = Field(default="")


class Signal(BaseModel):
    """Communication signal in the HLD."""
    name: str = Field(..., description="Signal name, e.g. 'S_EngineSpeed'")
    direction: str = Field(default="", description="TX, RX, or bidirectional")
    data_type: str = Field(default="", description="Data type, e.g. uint16, float32")
    unit: str = Field(default="", description="Physical unit, e.g. 'rpm', 'kPa'")
    source_swc: str = Field(default="", description="Source SWC name")
    target_swc: str = Field(default="", description="Target SWC name")
    description: str = Field(default="")


class Dependency(BaseModel):
    """Dependency link between two AUTOSAR components."""
    source: str = Field(..., description="Source entity name")
    target: str = Field(..., description="Target entity name")
    dependency_type: str = Field(
        default="uses",
        description="Relationship: uses, provides, requires, communicates_with",
    )
    via_interface: str = Field(default="", description="Interface mediating the dependency")
    description: str = Field(default="")


class DataFlow(BaseModel):
    """Data flow path between components."""
    source_swc: str = Field(..., description="Source SWC")
    target_swc: str = Field(..., description="Target SWC")
    signal_name: str = Field(default="", description="Signal carried")
    interface_name: str = Field(default="", description="Interface used")
    direction: str = Field(default="unidirectional")
    description: str = Field(default="")


# Mapping from entity_type string to schema class
ENTITY_SCHEMAS: dict[str, type[BaseModel]] = {
    "SWComponent": SWComponent,
    "Interface": Interface,
    "Signal": Signal,
    "Dependency": Dependency,
    "DataFlow": DataFlow,
}
