extends Node2D

@onready var tilemap = $TileMap

var level_data
var room_positions = {}
var occupied = {}

var directions = [
	Vector2i(1, 0),
	Vector2i(-1, 0),
	Vector2i(0, 1),
	Vector2i(0, -1)
]

func _ready():
	load_json()
	generate_level()

func load_json():
	var file = FileAccess.open("res://level.json", FileAccess.READ)
	var text = file.get_as_text()
	var result = JSON.parse_string(text)

	if result == null:
		print("Erro ao ler JSON")
	else:
		level_data = result

func generate_level():
	tilemap.clear()
	room_positions.clear()
	occupied.clear()

	if level_data == null:
		return

	position_rooms()
	generate_connections()

func position_rooms():
	var rooms = level_data["rooms"]
	var connections = level_data["connections"]
	var graph = {}

	for room in rooms:
		graph[room["id"]] = []

	for conn in connections:
		var start = conn[0]
		var end = conn[1]
		graph[start].append(end)
		graph[end].append(start)

	var start_id = -1

	for room in rooms:
		if room["type"] == "start":
			start_id = room["id"]
			break

	if start_id == -1:
		print("Erro: nenhuma sala inicial encontrada.")
		return

	var distance = {}
	var queue = []
	distance[start_id] = 0
	queue.append(start_id)

	while not queue.is_empty():
		var current = queue.pop_front()
		
		for neighbor in graph[current]:
			
			if not distance.has(neighbor):
				distance[neighbor] = (
					distance[current] + 1
				)

				queue.append(neighbor)

	var layers = {}

	for room in rooms:
		var id = room["id"]

		if not distance.has(id):
			distance[id] = 0

		var layer = distance[id]

		if not layers.has(layer):
			layers[layer] = []

		layers[layer].append(id)

	var sorted_layers = layers.keys()
	sorted_layers.sort()
	var horizontal_spacing = 5
	var vertical_spacing = 5

	for layer in sorted_layers:
		var layer_rooms = layers[layer]
		var count = layer_rooms.size()

		for i in range(count):
			var room_id = layer_rooms[i]
			
			var y_offset = (
				i - (count - 1) / 2.0
			)
			var x = layer * horizontal_spacing
			var y = int(
				y_offset * vertical_spacing
			)
			var pos = Vector2i(
				x,
				y
			)

			while occupied.has(pos):
				pos.y += vertical_spacing

			room_positions[
				room_id
			] = pos
			occupied[pos] = true

	for room in rooms:
		var id = room["id"]
		var pos = room_positions[id]
		draw_room(
			pos,
			room["type"]
		)

func draw_room(pos, type):
	var atlas_coords = Vector2i(0, 0)

	if type == "start":
		atlas_coords = Vector2i(1, 0)
	elif type == "boss":
		atlas_coords = Vector2i(2, 0)
	elif type == "enemy":
		atlas_coords = Vector2i(0, 0)
	elif type == "treasure":
		atlas_coords = Vector2i(3, 0)
	elif type == "key":
		atlas_coords = Vector2i(4, 0)
	elif type == "locked":
		atlas_coords = Vector2i(5, 0)

	for i in range(3):
		for j in range(3):
			tilemap.set_cell(
				0,
				pos + Vector2i(i, j),
				0,
				atlas_coords
			)

func generate_connections():
	var connections = level_data["connections"]

	for conn in connections:
		var start = room_positions[
			conn[0]
		]
		var end = room_positions[
			conn[1]
		]
		draw_corridor(
			start,
			end
		)

func draw_corridor(start, end):
	var pos = start

	while pos.x != end.x:
		pos.x += sign(
			end.x - pos.x
		)
		tilemap.set_cell(
			0,
			pos,
			0,
			Vector2i(0, 0)
		)

	while pos.y != end.y:
		pos.y += sign(
			end.y - pos.y
		)
		tilemap.set_cell(
			0,
			pos,
			0,
			Vector2i(0, 0)
		)
