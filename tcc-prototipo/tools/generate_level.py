from __future__ import annotations

import json
import sys
import re
from pathlib import Path
from typing import Literal

import requests
from pydantic import BaseModel, Field, ValidationError, model_validator

RoomType = Literal[
    "start",
    "enemy",
    "treasure",
    "boss",
    "key",
    "locked",
]

class Room(BaseModel):
    id: int = Field(ge=1)
    type: RoomType

class Connection(BaseModel):
    start: int
    end: int

class Dungeon(BaseModel):
    rooms: list[Room]
    connections: list[Connection]

    @model_validator(mode="after")
    def validate_dungeon(self) -> "Dungeon":

        ids = [room.id for room in self.rooms]

        if len(ids) != len(set(ids)):
            raise ValueError("Existem IDs de salas repetidos.")

        if sum(room.type == "start" for room in self.rooms) != 1:
            raise ValueError(
                "O nível deve conter exatamente uma sala inicial."
            )

        if sum(room.type == "boss" for room in self.rooms) != 1:
            raise ValueError(
                "O nível deve conter exatamente uma sala de chefe."
            )

        known_ids = set(ids)

        for connection in self.connections:

            if connection.start not in known_ids:
                raise ValueError(
                    f"A conexão referencia a sala inexistente "
                    f"{connection.start}."
                )

            if connection.end not in known_ids:
                raise ValueError(
                    f"A conexão referencia a sala inexistente "
                    f"{connection.end}."
                )

            if connection.start == connection.end:
                raise ValueError(
                    "Uma sala não pode se conectar a ela mesma."
                )

        return self

SYSTEM_PROMPT = """
Você é um projetista de níveis para jogos do tipo dungeon.

Sua tarefa é gerar a estrutura lógica de uma dungeon a partir da descrição fornecida pelo usuário.

A resposta deve ser EXCLUSIVAMENTE um objeto JSON válido.

NÃO:
- escreva explicações;
- escreva texto antes ou depois do JSON;
- utilize Markdown;
- utilize blocos de código;
- utilize ```json;
- adicione campos que não foram solicitados.

O formato obrigatório é:

{
    "rooms": [
        {
            "id": 1,
            "type": "start"
        },
        {
            "id": 2,
            "type": "enemy"
        },
        {
            "id": 3,
            "type": "boss"
        }
    ],
    "connections": [
        {
            "start": 1,
            "end": 2
        },
        {
            "start": 2,
            "end": 3
        }
    ]
}

REGRAS DAS SALAS:

- "rooms" deve ser uma lista de objetos.
- Cada sala deve possuir exatamente os campos "id" e "type".
- "id" deve ser um número inteiro positivo.
- Cada ID deve ser único.
- "type" deve ser exatamente um dos seguintes valores:
  - "start"
  - "enemy"
  - "treasure"
  - "boss"
  - "key"
  - "locked"
- Deve existir exatamente uma sala do tipo "start".
- Deve existir exatamente uma sala do tipo "boss".

REGRAS DAS CONEXÕES:

- "connections" deve ser uma lista de objetos.
- Cada conexão deve possuir exatamente os campos "start" e "end".
- "start" deve conter o ID de uma sala existente.
- "end" deve conter o ID de uma sala existente.
- "start" e "end" devem ser números inteiros.
- Uma sala não pode se conectar a ela mesma.
- Não utilize listas como [1, 2] para representar conexões.
- Uma conexão deve SEMPRE seguir este formato:

{
    "start": 1,
    "end": 2
}

REGRAS DA ESTRUTURA:

- Nenhuma sala deve ficar isolada.
- Deve existir um caminho entre a sala "start" e a sala "boss".
- O nível deve possuir alguma progressão lógica.
- Todas as conexões devem utilizar IDs de salas existentes.

IMPORTANTE:

Retorne somente o JSON.

A primeira coisa da resposta deve ser o caractere {
A última coisa da resposta deve ser o caractere }
"""

OLLAMA_URL = "http://localhost:11434/api/chat"

MODEL_NAME = "llama3.2"

MAX_ATTEMPTS = 3

CORRECTION_PROMPT = """
Sua resposta anterior não passou na validação.

Erros encontrados:

{errors}

Corrija APENAS esses erros.

Mantenha todas as demais informações.

Não gere uma dungeon diferente.

Não escreva explicações.

Não utilize Markdown.

Retorne somente JSON válido.
"""

def format_validation_errors(error: ValidationError) -> str:

    errors = []

    for item in error.errors():

        location = " → ".join(
            str(part)
            for part in item["loc"]
        )

        message = item["msg"]

        errors.append(
            f"- Campo '{location}': {message}"
        )

    return "\n".join(errors)

def validate_connectivity(dungeon: Dungeon) -> list[str]:
    errors = []

    start_room = next(
        room
        for room in dungeon.rooms
        if room.type == "start"
    )

    boss_room = next(
        room
        for room in dungeon.rooms
        if room.type == "boss"
    )

    graph: dict[int, list[int]] = {
        room.id: []
        for room in dungeon.rooms
    }

    for connection in dungeon.connections:

        graph[connection.start].append(
            connection.end
        )

        graph[connection.end].append(
            connection.start
        )

    for room in dungeon.rooms:

        if len(graph[room.id]) == 0:

            errors.append(
                f"A sala {room.id} "
                f"(tipo '{room.type}') está isolada "
                f"e não possui nenhuma conexão."
            )

    visited = set()

    queue = [start_room.id]

    while queue:

        current = queue.pop(0)

        if current in visited:
            continue

        visited.add(current)

        for neighbor in graph[current]:

            if neighbor not in visited:
                queue.append(neighbor)

    if boss_room.id not in visited:

        errors.append(
            f"A sala boss (id {boss_room.id}) "
            f"não é alcançável a partir da sala "
            f"start (id {start_room.id})."
        )

    return errors

def validate_logic(dungeon: Dungeon) -> list[str]:
    errors = []
    connections_seen = set()

    for connection in dungeon.connections:
        connection_key = tuple(
            sorted(
                [connection.start, connection.end]
            )
        )

        if connection_key in connections_seen:

            errors.append(
                f"A conexão entre as salas "
                f"{connection.start} e {connection.end} "
                f"está duplicada."
            )

        else:

            connections_seen.add(
                connection_key
            )

    has_key = any(
        room.type == "key"
        for room in dungeon.rooms
    )

    has_locked = any(
        room.type == "locked"
        for room in dungeon.rooms
    )

    if has_locked and not has_key:

        errors.append(
            "Existe pelo menos uma sala do tipo "
            "'locked', mas não existe nenhuma "
            "sala do tipo 'key'."
        )

    return errors

def validate_requirements(
    dungeon: Dungeon,
    description: str
) -> list[str]:
    
    errors = []
    description_lower = description.lower()
    
    room_type_names = {
        "start": ["start", "inicial", "início", "inicio"],
        "enemy": ["enemy", "inimigo", "inimigos"],
        "treasure": ["treasure", "tesouro"],
        "boss": ["boss", "chefe"],
        "key": ["key", "chave"],
        "locked": ["locked", "trancada", "trancado"],
    }
    
    number_words = {
        "um": 1,
        "uma": 1,
        "dois": 2,
        "duas": 2,
        "três": 3,
        "tres": 3,
        "quatro": 4,
        "cinco": 5,
        "seis": 6,
        "sete": 7,
        "oito": 8,
        "nove": 9,
        "dez": 10,
        "onze": 11,
        "doze": 12,
        "treze": 13,
        "quatorze": 14,
        "quinze": 15,
    }
    
    requested_counts: dict[str, int] = {}
    
    for room_type, names in room_type_names.items():
        for name in names:
            pattern_word = (
                r"\b("
                + "|".join(
                    number_words.keys()
                )
                + r")\s+"
                r"(?:salas?\s+de\s+)?"
                + re.escape(name)
                + r"\b"
            )

            match = re.search(
                pattern_word,
                description_lower
            )

            if match:

                number = number_words[
                    match.group(1)
                ]

                requested_counts[
                    room_type
                ] = number

                break

            pattern_digit = (
                r"\b(\d+)\s+"
                r"(?:salas?\s+de\s+)?"
                + re.escape(name)
                + r"\b"
            )

            match = re.search(
                pattern_digit,
                description_lower
            )

            if match:

                requested_counts[
                    room_type
                ] = int(
                    match.group(1)
                )

                break

    special_patterns = {
        "start": [
            r"\buma\s+sala\s+(?:de\s+)?inicial\b",
            r"\buma\s+sala\s+(?:de\s+)?start\b",
        ],

        "boss": [
            r"\buma\s+sala\s+(?:de\s+)?chefe\b",
            r"\buma\s+sala\s+(?:de\s+)?boss\b",
        ],

        "treasure": [
            r"\buma\s+sala\s+(?:de\s+)?tesouro\b",
        ],

        "key": [
            r"\buma\s+sala\s+(?:de\s+)?chave\b",
        ],

        "locked": [
            r"\buma\s+sala\s+(?:de\s+)?"
            r"(?:trancada|trancado)\b",
        ],
    }

    for room_type, patterns in special_patterns.items():
        if room_type in requested_counts:
            continue

        for pattern in patterns:
            if re.search(
                pattern,
                description_lower
            ):

                requested_counts[
                    room_type
                ] = 1

                break

    actual_counts = {}

    for room_type in room_type_names:
        actual_counts[room_type] = sum(
            room.type == room_type
            for room in dungeon.rooms
        )

    for room_type, expected in requested_counts.items():
        actual = actual_counts[
            room_type
        ]

        if actual != expected:
            errors.append(
                f"A descrição solicita "
                f"{expected} sala(s) do tipo "
                f"'{room_type}', mas foram "
                f"geradas {actual}."
            )

    if requested_counts:
        expected_total = sum(
            requested_counts.values()
        )

        actual_total = len(
            dungeon.rooms
        )

        if (
            actual_total != expected_total
            and all(
                room.type in requested_counts
                for room in dungeon.rooms
            )
        ):

            errors.append(
                f"A descrição solicita "
                f"{expected_total} sala(s) "
                f"no total, mas foram "
                f"geradas {actual_total}."
            )

    return errors

def call_llm(messages: list[dict]) -> str:
    print("Enviando requisição para Ollama...")
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.1
            }
        },
        timeout=240,
    )
    
    print("Ollama respondeu.")
    response.raise_for_status()
    print("Status HTTP:", response.status_code)
    text = response.json()["message"]["content"].strip()
    print("Resposta recebida.")
    
    if text.startswith("```"):

        text = text.replace(
            "```json",
            ""
        )

        text = text.replace(
            "```",
            ""
        )

        text = text.strip()

    return text

def validate_response(text: str) -> Dungeon:

    data = json.loads(text)

    return Dungeon.model_validate(data)

def generate_dungeon(description: str) -> Dungeon:

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        {
            "role": "user",
            "content": description
        }
    ]

    last_error = None

    for attempt in range(
        1,
        MAX_ATTEMPTS + 1
    ):

        print(
            f"\nTentativa "
            f"{attempt}/{MAX_ATTEMPTS}"
        )

        try:

            response_text = call_llm(
                messages
            )

            dungeon = validate_response(
                response_text
            )

            connectivity_errors = validate_connectivity(dungeon)
            logic_errors = validate_logic(dungeon)

            requirement_errors = validate_requirements(
                dungeon,
                description
            )

            all_logic_errors = (
                connectivity_errors
                + logic_errors
                + requirement_errors
            )
            
            if all_logic_errors:
                formatted_errors = "\n".join(
                    f"- {error}"
                    for error in all_logic_errors
                )

                print("\nErros de lógica:")
                print(formatted_errors)
                last_error = formatted_errors

                messages.append(
                    {
                        "role": "assistant",
                        "content": response_text
                    }
                )

                messages.append(
                    {
                        "role": "user",
                        "content": CORRECTION_PROMPT.format(
                            errors=formatted_errors
                        )
                    }
                )

                continue

            print(
                "Dungeon válida."
            )

            return dungeon

        except json.JSONDecodeError as error:

            last_error = error

            formatted_errors = (
                "A resposta não é um JSON válido.\n"
                f"Erro: {error.msg}\n"
                f"Posição aproximada do erro: {error.pos}"
            )

            print(
                "\nJSON inválido."
            )

            print(
                formatted_errors
            )

            messages.append(
                {
                    "role": "assistant",
                    "content": response_text
                }
            )

            messages.append(
                {
                    "role": "user",
                    "content": CORRECTION_PROMPT.format(
                        errors=formatted_errors
                    )
                }
            )

        except ValidationError as error:

            last_error = error

            formatted_errors = (
                format_validation_errors(
                    error
                )
            )

            print(
                "\nErro de validação."
            )

            print(
                formatted_errors
            )

            messages.append(
                {
                    "role": "assistant",
                    "content": response_text
                }
            )

            messages.append(
                {
                    "role": "user",
                    "content": CORRECTION_PROMPT.format(
                        errors=formatted_errors
                    )
                }
            )

    raise RuntimeError(
        f"Não foi possível gerar uma "
        f"dungeon válida após "
        f"{MAX_ATTEMPTS} tentativas.\n\n"
        f"Último erro:\n"
        f"{last_error}"
    )

def save_for_godot(
    dungeon: Dungeon,
    output_path: Path
) -> None:

    godot_data = {
        "rooms": [
            {
                "id": room.id,
                "type": room.type,
            }
            for room in dungeon.rooms
        ],
        "connections": [
            [
                connection.start,
                connection.end
            ]
            for connection in dungeon.connections
        ]
    }

    output_path.write_text(
        json.dumps(
            godot_data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

def main() -> int:

    project_root = (
        Path(__file__).resolve().parent.parent
    )

    output_path = (
        project_root / "level.json"
    )

    description = (
        " ".join(sys.argv[1:]).strip()
        or input(
            "Descreva o nível desejado: "
        ).strip()
    )

    if not description:

        print(
            "A descrição do nível "
            "não pode estar vazia."
        )

        return 1

    try:

        dungeon = generate_dungeon(
            description
        )

        save_for_godot(
            dungeon,
            output_path,
        )

    except Exception as error:

        print(
            f"\nErro ao gerar o nível:\n"
            f"{error}"
        )

        return 1

    print(
        "\nDungeon gerada com sucesso!"
    )

    print(
        f"Arquivo: {output_path}"
    )

    print(
        f"Salas: {len(dungeon.rooms)}"
    )

    print(
        f"Conexões: {len(dungeon.connections)}"
    )

    return 0

if __name__ == "__main__":
    raise SystemExit(main())