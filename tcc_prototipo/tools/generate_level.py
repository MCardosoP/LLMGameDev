from __future__ import annotations

import json
import sys
import re
from pathlib import Path
from typing import Literal
from datetime import datetime
from time import perf_counter

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

Sua tarefa é gerar a estrutura lógica de uma dungeon a partir da descrição do usuário.

Retorne EXCLUSIVAMENTE um objeto JSON válido.
Não escreva explicações, Markdown, blocos de código ou texto antes/depois do JSON.

Formato obrigatório:

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

- "rooms" deve ser uma lista de objetos contendo apenas "id" e "type".
- "id" deve ser um inteiro positivo e único.
- "type" deve ser exatamente "start", "enemy", "treasure", "boss", "key" ou "locked".
- Deve existir exatamente uma sala "start" e exatamente uma sala "boss".
- Respeite exatamente os tipos e as quantidades de salas solicitados pelo usuário.
- Não adicione salas de tipos não solicitados.
- Siga a progressão e a estrutura descritas pelo usuário.
- Não adicione salas ou conexões que não contribuam para a estrutura solicitada.
- A sala "boss" deve ser o destino final da progressão, salvo quando o usuário solicitar explicitamente outra estrutura.
- Quando forem solicitados múltiplos caminhos, mantenha-os distintos até o ponto de encontro especificado pelo usuário.

REGRAS DAS CONEXÕES:

- "connections" deve ser uma lista de objetos contendo apenas "start" e "end".
- "start" e "end" devem ser inteiros correspondentes a IDs de salas existentes.
- Uma sala não pode se conectar a ela mesma.
- Nunca represente uma conexão como uma lista, por exemplo [1, 2].
- Cada conexão deve seguir o formato:
  {
      "start": 1,
      "end": 2
  }

REGRAS DA ESTRUTURA:

- Nenhuma sala deve ficar isolada.
- Deve existir um caminho entre "start" e "boss".
- Todas as conexões devem utilizar IDs existentes.
- O nível deve possuir uma progressão lógica.

A resposta deve começar com { e terminar com }.
"""

OLLAMA_URL = "http://localhost:11434/api/chat"

MODEL_NAME = "qwen2.5:7b"

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

    start_rooms = [
        room
        for room in dungeon.rooms
        if room.type == "start"
    ]

    if start_rooms:

        start_id = start_rooms[0].id

        for connection in dungeon.connections:

            if connection.end == start_id:

                errors.append(
                    f"A sala inicial {start_id} "
                    f"possui uma conexão de entrada."
                )

                break

    boss_rooms = [
        room
        for room in dungeon.rooms
        if room.type == "boss"
    ]

    if boss_rooms:

        boss_id = boss_rooms[0].id
        
        for connection in dungeon.connections:

            if connection.start == boss_id:

                errors.append(
                    f"A sala boss {boss_id} "
                    f"possui uma conexão de saída."
                )

                break
    
    return errors

def validate_requirements(
    dungeon: Dungeon,
    description: str
) -> list[str]:
    
    errors = []
    description_lower = description.lower()
    
    mandatory_types = {
        "start",
        "boss",
    }

    room_type_names = {
        "start": ["start", "inicial", "início", "inicio"],
        "enemy": ["enemy", "inimigo", "inimigos"],
        "treasure": ["treasure", "tesouro", "recompensa", "recompensas"],
        "boss": ["boss", "chefe", "final"],
        "key": ["key", "chave"],
        "locked": [
            "locked",
            "trancada",
            "trancado",
        ],
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

    mentioned_types = set()

    for room_type, names in room_type_names.items():
        for name in names:
            if re.search(
                r"\b" + re.escape(name) + r"\b",
                description_lower
            ):
                mentioned_types.add(room_type)
                break

    requested_counts: dict[str, int] = {}

    number_pattern = "|".join(
        number_words.keys()
    )

    for room_type, names in room_type_names.items():
        for name in names:
            pattern_word = (
                r"\b("
                + number_pattern
                + r")\s+"
                r"salas?\s+"
                r"(?:de\s+)?"
                + re.escape(name)
                + r"\b"
            )

            match = re.search(
                pattern_word,
                description_lower
            )

            if match:

                requested_counts[
                    room_type
                ] = number_words[
                    match.group(1)
                ]

                break

            pattern_digit = (
                r"\b(\d+)\s+"
                r"salas?\s+"
                r"(?:de\s+)?"
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
            r"\buma\s+recompensa\b"
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

                mentioned_types.add(
                    room_type
                )

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

    for room_type in mentioned_types:
        if room_type in mandatory_types:
            continue
        
        if room_type in requested_counts:
            continue
        
        actual = actual_counts[room_type]
        
        if actual == 0:
            errors.append(
                f"A descrição solicita salas do tipo "
                f"'{room_type}', mas nenhuma foi gerada."
            )

    if mentioned_types:
        for room_type in room_type_names:
            if room_type in mandatory_types:
                continue
                
            if room_type in mentioned_types:
                continue

            actual = actual_counts[room_type]

            if actual > 0:
                errors.append(
                    f"A descrição não solicita "
                    f"salas do tipo '{room_type}', "
                    f"mas foram geradas {actual}."
                )

    return errors

def validate_structure(
    dungeon: Dungeon,
    description: str
) -> list[str]:
    errors = []
    description_lower = description.lower()

    requires_two_paths = (
        (
            "dois caminhos" in description_lower
            or "duas caminhos" in description_lower
        )
        and (
            "se encontram" in description_lower
            or "se encontre" in description_lower
            or "encontram" in description_lower
        )
        and (
            "chefe" in description_lower
            or "boss" in description_lower
        )
    )

    if not requires_two_paths:
        return errors

    start_rooms = [
        room.id
        for room in dungeon.rooms
        if room.type == "start"
    ]

    boss_rooms = [
        room.id
        for room in dungeon.rooms
        if room.type == "boss"
    ]

    if not start_rooms or not boss_rooms:
        return errors

    start_id = start_rooms[0]
    boss_id = boss_rooms[0]

    graph: dict[int, set[int]] = {
        room.id: set()
        for room in dungeon.rooms
    }

    for connection in dungeon.connections:

        graph[
            connection.start
        ].add(
            connection.end
        )

        graph[
            connection.end
        ].add(
            connection.start
        )

    def find_path(
        blocked_edges: set[tuple[int, int]]
    ) -> list[int] | None:

        queue = [start_id]

        previous: dict[
            int,
            int | None
        ] = {
            start_id: None
        }

        while queue:
            current = queue.pop(0)

            if current == boss_id:
                break

            for neighbor in graph[current]:
                edge = tuple(
                    sorted(
                        (
                            current,
                            neighbor
                        )
                    )
                )

                if edge in blocked_edges:
                    continue

                if neighbor in previous:
                    continue

                previous[neighbor] = current
                queue.append(neighbor)

        if boss_id not in previous:
            return None

        path = []
        current = boss_id

        while current is not None:
            path.append(current)
            current = previous[current]

        path.reverse()
        return path

    first_path = find_path(set())

    if first_path is None:
        errors.append(
            "Não existe um caminho entre "
            "a sala inicial e a sala de chefe."
        )

        return errors

    blocked_edges = set()

    for i in range(
        len(first_path) - 1
    ):

        edge = tuple(
            sorted(
                (
                    first_path[i],
                    first_path[i + 1]
                )
            )
        )

        blocked_edges.add(edge)

    second_path = find_path(
        blocked_edges
    )

    if second_path is None:
        errors.append(
            "A descrição solicita dois caminhos "
            "diferentes entre a sala inicial e "
            "a sala de chefe, mas a dungeon "
            "possui apenas um caminho."
        )

        return errors

    if first_path[-1] != boss_id:
        errors.append(
            "O primeiro caminho não termina "
            "na sala de chefe."
        )

    if second_path[-1] != boss_id:
        errors.append(
            "O segundo caminho não termina "
            "na sala de chefe."
        )

    if len(graph[boss_id]) > 2:
        errors.append(
            "A sala de chefe deve ser o ponto "
            "final onde os caminhos se encontram. "
            "Não devem existir conexões adicionais "
            "depois da sala de chefe."
        )

    first_internal = set(
        first_path[1:-1]
    )

    second_internal = set(
        second_path[1:-1]
    )

    common_internal = (
        first_internal
        & second_internal
    )

    if common_internal:
        errors.append(
            "A dungeon deve possuir dois "
            "caminhos distintos entre START "
            "e BOSS. Os dois caminhos podem "
            "compartilhar apenas a sala inicial "
            "e a sala de chefe."
        )

    return errors

def call_llm(messages: list[dict]) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL_NAME,
            "messages": messages,
            "stream": False,
            "format": Dungeon.model_json_schema(),
            "options": {
                "temperature": 0.3,   # 0.1 favorece loops de repetição
                "num_predict": 700,   # teto de tokens; ajuste conforme o tamanho da dungeon
                "num_ctx": 4096,
            },
        },
        timeout=(10, 120),
    )
    response.raise_for_status()
    body = response.json()

    print(
        f"tokens: {body.get('eval_count')} | "
        f"fim: {body.get('done_reason')} | "
        f"{body.get('total_duration', 0) / 1e9:.1f}s"
    )

    return body["message"]["content"].strip()

def validate_response(text: str) -> Dungeon:
    data = json.loads(text)
    return Dungeon.model_validate(data)

def generate_dungeon(description: str) -> tuple[Dungeon, list[dict]]:
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
    attempts_log = []

    for attempt in range(
        1,
        MAX_ATTEMPTS + 1
    ):

        attempt_start = perf_counter()

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
            
            structure_errors = validate_structure(
                dungeon,
                description
            )

            all_logic_errors = (
                connectivity_errors
                + logic_errors
                + requirement_errors
                + structure_errors
            )
            
            if all_logic_errors:
                formatted_errors = "\n".join(
                    f"- {error}"
                    for error in all_logic_errors
                )

                print("\nErros de lógica:")
                print(formatted_errors)
                last_error = formatted_errors

                attempts_log.append(
                    {
                        "attempt": attempt,
                        "valid": False,
                        "dungeon": dungeon.model_dump(),
                        "errors": all_logic_errors,
                        "time_seconds": round(
                            perf_counter() - attempt_start,
                            2
                        ),
                    }
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

                continue

            print(
                "Dungeon válida."
            )
            
            attempts_log.append(
                {
                    "attempt": attempt,
                    "valid": True,
                    "dungeon": dungeon.model_dump(),
                    "errors": [],
                    "time_seconds": round(
                        perf_counter() - attempt_start,
                        2
                    ),
                }
            )

            return dungeon, attempts_log

        except json.JSONDecodeError as error:
            last_error = error

            formatted_errors = (
                "A resposta não é um JSON válido.\n"
                f"Erro: {error.msg}\n"
                f"Posição aproximada do erro: {error.pos}"
            )

            attempts_log.append(
                {
                    "attempt": attempt,
                    "valid": False,
                    "dungeon": None,
                    "errors": [formatted_errors],
                    "time_seconds": round(
                        perf_counter() - attempt_start,
                        2
                    ),
                }
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

            attempts_log.append(
                {
                    "attempt": attempt,
                    "valid": False,
                    "dungeon": None,
                    "errors": [formatted_errors],
                    "time_seconds": round(
                        perf_counter() - attempt_start,
                        2
                    ),
                }
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

def save_experiment_log(
    experiment_number: int,
    description: str,
    attempts: list[dict],
    total_time_seconds: float,
    output_path: Path,
) -> None:

    experiment_data = {
        "experiment": experiment_number,
        "description": description,
        "timestamp": datetime.now().isoformat(),
        "success": bool(attempts and attempts[-1]["valid"]),
        "total_attempts": len(attempts),
        "total_time_seconds": round(total_time_seconds, 2),
        "attempts": attempts,
    }

    output_path.write_text(
        json.dumps(
            experiment_data,
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
    
    experiments_path = (
        project_root / "experiments"
    )
    
    experiments_path.mkdir(
        exist_ok=True
    )

    description = (
        " ".join(sys.argv[1:]).strip()
        or input(
            "Descreva o nível desejado: "
        ).strip()
    )
    
    experiment_number_text = input(
        "Número do experimento: "
    ).strip()

    if not description:
        print(
            "A descrição do nível "
            "não pode estar vazia."
        )
        return 1

    if not experiment_number_text.isdigit():
        print(
            "O número do experimento deve ser um número inteiro."
        )
        return 1
    
    experiment_number = int(
        experiment_number_text
    )

    try:
        experiment_start = perf_counter()

        dungeon, attempts_log = generate_dungeon(
            description
        )

        total_time_seconds = perf_counter() - experiment_start

        save_for_godot(
            dungeon,
            output_path,
        )
        
        experiment_output_path = (
            experiments_path
            / f"experiment_{experiment_number:02d}.json"
        )
        
        save_experiment_log(
            experiment_number,
            description,
            attempts_log,
            total_time_seconds,
            experiment_output_path
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