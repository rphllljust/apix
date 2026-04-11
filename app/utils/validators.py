"""Responsabilidade: implementa o modulo app/utils/validators.py."""

from __future__ import annotations

import re

from app.exceptions import ValidationError


def normalize_cpf(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\D", "", value)


def is_valid_cpf(cpf: str) -> bool:
    if not cpf or len(cpf) != 11 or len(set(cpf)) == 1:
        return False

    digits = [int(number) for number in cpf]
    first_sum = sum(digits[i] * (10 - i) for i in range(9))
    first_digit = ((first_sum * 10) % 11) % 10
    if first_digit != digits[9]:
        return False

    second_sum = sum(digits[i] * (11 - i) for i in range(10))
    second_digit = ((second_sum * 10) % 11) % 10
    return second_digit == digits[10]


def is_valid_email(email: str | None) -> bool:
    if not email:
        return False
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def assert_valid_cpf(cpf: str) -> None:
    if not is_valid_cpf(cpf):
        raise ValidationError("CPF invalido.")


def assert_valid_email(email: str) -> None:
    if not is_valid_email(email):
        raise ValidationError("Email invalido.")

