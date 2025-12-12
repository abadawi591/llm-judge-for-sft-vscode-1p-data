"""
Schemas Module
==============

Data schemas for input conversations and output labels.

This module defines the structure of:
    - Input data (conversations with turns)
    - Output data (labeled turns)

Input Schema (from Kusto export):
    Each conversation has multiple turns, each turn contains:
    - turnIndex: Position in conversation (1-indexed)
    - messageId: Unique identifier for the turn
    - userMessage: The user's input text
    - modelMessage: The model's response
    - llmCalls: Token usage and model info
    - tools: Tool definitions and invocations

Output Schema (minimal):
    Each labeled turn contains only:
    - conversationId: Links back to original data
    - messageId: Links back to specific turn
    - hard_label: Binary label (0 or 1)
    - soft_label: Probability in [0, 1]
    - rationale: Human-readable explanation
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class TurnRecord:
    """
    A single turn (user message) to be labeled.
    
    This is the input unit for the labeling pipeline. Each turn
    represents one user message within a conversation.
    
    Attributes:
        conversation_id: Unique ID of the parent conversation
        message_id: Unique ID of this specific turn
        turn_index: Position in conversation (1 = first turn)
        user_message: The user's input text (what we classify)
        model_message: The model's response (optional context)
        bucket: Turn count bucket (short/medium/long)
        split: Data split (train/val/test)
    """
    conversation_id: str
    message_id: str
    turn_index: int
    user_message: str
    model_message: Optional[str] = None
    bucket: Optional[str] = None
    split: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "conversationId": self.conversation_id,
            "messageId": self.message_id,
            "turnIndex": self.turn_index,
            "userMessage": self.user_message,
            "modelMessage": self.model_message,
            "bucket": self.bucket,
            "split": self.split,
        }
    
    @classmethod
    def from_dict(cls, data: dict, conversation_id: str, bucket: str = None, split: str = None) -> "TurnRecord":
        """Create from turn dictionary within a conversation."""
        return cls(
            conversation_id=conversation_id,
            message_id=data.get("messageId", ""),
            turn_index=data.get("turnIndex", 0),
            user_message=data.get("userMessage", ""),
            model_message=data.get("modelMessage"),
            bucket=bucket,
            split=split,
        )


@dataclass
class LabeledTurnRecord:
    """
    Output schema for a labeled turn.
    
    This contains IDs, provenance info, and labels.
    Original data can be recovered by joining on conversation_id + message_id.
    
    Attributes:
        conversation_id: Links to original conversation
        message_id: Links to specific turn
        split: Data split (train/val/test) - provenance, NOT passed to LLM
        bucket: Stratification bucket - provenance, NOT passed to LLM
        hard_label: Binary classification (0=reasoning, 1=non-reasoning)
        soft_label: Probability of label 1 in [0, 1]
        rationale: Human-readable explanation
        error: Error message if labeling failed
    """
    conversation_id: str
    message_id: str
    split: Optional[str] = None
    bucket: Optional[str] = None
    hard_label: Optional[int] = None
    soft_label: Optional[float] = None
    rationale: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        """
        Convert to output dictionary.
        
        Includes provenance fields (split, bucket) for tracking where
        the turn came from. These are NOT passed to the LLM judge.
        """
        result = {
            "conversationId": self.conversation_id,
            "messageId": self.message_id,
        }
        
        # Add provenance fields (always include for tracking)
        if self.split:
            result["split"] = self.split
        if self.bucket:
            result["bucket"] = self.bucket
        
        if self.error:
            result["labeling_error"] = self.error
        else:
            result["hard_label"] = self.hard_label
            result["soft_label"] = round(self.soft_label, 4) if self.soft_label is not None else None
            if self.rationale:
                result["rationale"] = self.rationale
        
        return result
    
    @classmethod
    def from_turn_and_result(
        cls,
        turn: TurnRecord,
        hard_label: int,
        soft_label: float,
        rationale: str = None,
    ) -> "LabeledTurnRecord":
        """Create from a turn and classification result."""
        return cls(
            conversation_id=turn.conversation_id,
            message_id=turn.message_id,
            split=turn.split,
            bucket=turn.bucket,
            hard_label=hard_label,
            soft_label=soft_label,
            rationale=rationale,
        )
    
    @classmethod
    def from_error(cls, turn: TurnRecord, error: str) -> "LabeledTurnRecord":
        """Create error record for failed labeling."""
        return cls(
            conversation_id=turn.conversation_id,
            message_id=turn.message_id,
            split=turn.split,
            bucket=turn.bucket,
            error=error,
        )


@dataclass
class ConversationRecord:
    """
    A complete conversation with all turns.
    
    Used for loading data from blob storage before flattening to turns.
    
    Attributes:
        conversation_id: Unique conversation identifier
        user_name: User identifier (anonymized)
        bucket: Turn count bucket (short_3_to_5_turns, etc.)
        turn_count: Number of turns in conversation
        turns: List of turn data dictionaries
        split: Data split (train/val/test)
    """
    conversation_id: str
    user_name: Optional[str]
    bucket: str
    turn_count: int
    turns: List[Dict[str, Any]]
    split: Optional[str] = None
    
    def to_turn_records(self) -> List[TurnRecord]:
        """Flatten conversation to individual turn records."""
        return [
            TurnRecord.from_dict(turn, self.conversation_id, self.bucket, self.split)
            for turn in self.turns
        ]
    
    @classmethod
    def from_dict(cls, data: dict, split: str = None) -> "ConversationRecord":
        """Create from conversation dictionary."""
        return cls(
            conversation_id=data.get("conversationId", ""),
            user_name=data.get("userName"),
            bucket=data.get("bucket", ""),
            turn_count=data.get("turnCount", len(data.get("turnsArray", []))),
            turns=data.get("turnsArray", []),
            split=split,
        )

