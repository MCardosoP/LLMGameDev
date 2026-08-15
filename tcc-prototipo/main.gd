extends Node2D

@onready var tilemap = $TileMap
@onready var camera = $Camera2D

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
	
	var rooms = level_data["rooms"]
	var current_pos = Vector2i(0, 0)

	for room in rooms:
		room_positions[room["id"]] = current_pos
		occupied[current_pos] = true

		draw_room(current_pos, room["type"])

		var tries = 0
		var next_pos

		while tries < 10:
			var dir = directions[randi() % directions.size()]
			next_pos = current_pos + dir * 5

			if not occupied.has(next_pos):
				break

			tries += 1

		current_pos = next_pos

	generate_connections()
	adjust_camera()

func draw_room(pos, type):
	var atlas_coords = Vector2i(0,0)

	if type == "start":
		atlas_coords = Vector2i(1,0)
	elif type == "boss":
		atlas_coords = Vector2i(2,0)
	elif type == "enemy":
		atlas_coords = Vector2i(0,0)

	for i in range(3):
		for j in range(3):
			tilemap.set_cell(0, pos + Vector2i(i, j), 0, atlas_coords)

func generate_connections():
	var connections = level_data["connections"]

	for conn in connections:
		var start = room_positions[conn[0]]
		var end = room_positions[conn[1]]

		draw_corridor(start, end)

func draw_corridor(start, end):
	var pos = start

	while pos.x != end.x:
		pos.x += sign(end.x - pos.x)
		tilemap.set_cell(0, pos, 0, Vector2i(0,0))

	while pos.y != end.y:
		pos.y += sign(end.y - pos.y)
		tilemap.set_cell(0, pos, 0, Vector2i(0,0))

func adjust_camera():
	var used_rect = tilemap.get_used_rect()
	
	if used_rect.size == Vector2i.ZERO:
		return
	
	var tile_size = Vector2(tilemap.tile_set.tile_size)
	var map_size = Vector2(used_rect.size) * tile_size
	var center = (Vector2(used_rect.position) * tile_size) + map_size / 2.0
	camera.position = center
	var viewport = get_viewport_rect().size
	var zoom_x = map_size.x / viewport.x
	var zoom_y = map_size.y / viewport.y
	var zoom_factor = max(zoom_x, zoom_y, 1.0)
	camera.zoom = Vector2(zoom_factor, zoom_factor) * 1.1
