# -*- coding: utf-8 -*-
"""Pydantic-схемы валидации запросов и ответов REST API (FastAPI)."""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class AuthRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: Optional[str] = ""
    passHash: Optional[str] = ""
    display_name: Optional[str] = None
    displayName: Optional[str] = None
    state: Optional[Dict[str, Any]] = None


class AuthLoginRequest(BaseModel):
    username: str
    password: Optional[str] = ""
    passHash: Optional[str] = ""


class MealItemSchema(BaseModel):
    name: str
    mealType: str = "breakfast"
    grams: int = Field(default=150, gt=0)
    kcal: int = 0
    p: float = 0.0
    f: float = 0.0
    c: float = 0.0
    kcal100: Optional[int] = 0
    p100: Optional[float] = 0.0
    f100: Optional[float] = 0.0
    c100: Optional[float] = 0.0
    isLiquid: Optional[bool] = False
    liquidMl: Optional[int] = 0
    isCustomDish: Optional[bool] = False
    photo: Optional[str] = ""
    time: Optional[str] = "12:00"
    productId: Optional[str] = None


class DayDataSchema(BaseModel):
    meals: List[MealItemSchema] = []
    waterMl: int = 0
    freezeUsed: Optional[bool] = False
    penaltyRedeemed: Optional[bool] = False
    simulatedMiss: Optional[bool] = False
    _clearedByUser: Optional[bool] = False
    _explicitEditAt: Optional[int] = None


class WeightLogItemSchema(BaseModel):
    date: str
    kg: float


class CustomProductSchema(BaseModel):
    id: Optional[str] = None
    name: str
    brand: Optional[str] = ""
    category: Optional[str] = "Мои блюда"
    icon: Optional[str] = "🍲"
    kcal100: int = 100
    p100: float = 0.0
    f100: float = 0.0
    c100: float = 0.0
    portion: int = 100
    custom: bool = True
    isLiquid: Optional[bool] = False


class FullStateSyncSchema(BaseModel):
    goals: Dict[str, Any] = {}
    profile: Dict[str, Any] = {}
    days: Dict[str, Any] = {}
    weightLog: List[WeightLogItemSchema] = []
    customProducts: List[CustomProductSchema] = []
    recentItems: List[Dict[str, Any]] = []
    apiKey: Optional[str] = ""
    theme: Optional[str] = "dark"
    onboarded: Optional[bool] = True
    registeredDate: Optional[str] = None
    purchasedShields: Optional[int] = 0
    spentShieldXp: Optional[int] = 0
    bonusXp: Optional[int] = 0
    lastSeenLevel: Optional[int] = 1
    cloudConfig: Optional[Dict[str, Any]] = None
