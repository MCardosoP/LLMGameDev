extends Node2D

@onready var tilemap = $TileMap
@onready var camera = $Camera2D

var level_data
var room_positions = {}
var occupied = {}
var experiment_files = []

var directions = [
	Vector2i(1, 0),
	Vector2i(-1, 0),
	Vector2i(0, 1),
	Vector2i(0, -1)
]

func _ready():
	load_experiments()

func load_experiments():
	var directory = DirAccess.open(
		"res://experiments"
	)
	
	if directory == null:
		print("Erro: pasta experiments não encontrada.")
		return
	
	experiment_files.clear()
	directory.list_dir_begin()
	var file_name = directory.get_next()
	
	while file_name != "":
		if (
			not directory.current_is_dir()
			and file_name.ends_with(".json")
		):
			experiment_files.append(file_name)
		
		file_name = directory.get_next()
	
	directory.list_dir_end()
	experiment_files.sort()
	
	if experiment_files.is_empty():
		print("Nenhum experimento encontrado.")
		return
	
	show_experiment_selection()

func show_experiment_selection():
	var panel = Panel.new()
	panel.name = "ExperimentSelection"
	panel.position = Vector2(50, 50)

	panel.size = Vector2(
		300,
		100 + experiment_files.size() * 40
	)

	add_child(panel)
	var title = Label.new()
	title.text = "Escolha um experimento:"

	title.position = Vector2(20, 15)
	panel.add_child(title)

	for i in range(experiment_files.size()):
		var button = Button.new()
		button.text = experiment_files[i]

		button.position = Vector2(
			20,
			50 + i * 40
		)

		button.size = Vector2(250, 30)

		button.pressed.connect(
			load_selected_experiment.bind(
				experiment_files[i],
				panel
			)
		)

		panel.add_child(button)

func load_selected_experiment(
	file_name,
	panel
):
	var file = FileAccess.open(
		"res://experiments/" + file_name,
		FileAccess.READ
	)

	if file == null:
		print("Erro ao abrir: ", file_name)
		return

	var text = file.get_as_text()
	var result = JSON.parse_string(text)

	if result == null:
		print("Erro ao ler JSON: ", file_name)
		return

	var attempts = result.get("attempts", [])

	# Procura a última tentativa válida
	for i in range(attempts.size() - 1, -1, -1):
		var attempt = attempts[i]

		if attempt.get("valid", false):
			level_data = attempt.get("dungeon")

			if level_data == null:
				print("Erro: dungeon não encontrada no experimento.")
				return

			# Converte as conexões para o formato usado pelo Godot
			var converted_connections = []

			for connection in level_data["connections"]:
				converted_connections.append([
					connection["start"],
					connection["end"]
				])

			level_data["connections"] = converted_connections

			panel.queue_free()
			generate_level()
			return

	print("Nenhuma tentativa válida encontrada em: ", file_name)

func generate_level():
	tilemap.clear()
	room_positions.clear()
	occupied.clear()

	if level_data == null:
		return

	position_rooms()
	generate_connections()
	fit_camera_to_dungeon()

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
		
func fit_camera_to_dungeon():
	var used_rect = tilemap.get_used_rect()

	if used_rect.size == Vector2i.ZERO:
		return

	var tile_size = Vector2(tilemap.tile_set.tile_size)

	var dungeon_center = (
		Vector2(used_rect.position)
		+ Vector2(used_rect.size) / 2.0
	) * tile_size

	camera.position = dungeon_center

	var viewport_size = get_viewport_rect().size

	var dungeon_size = Vector2(used_rect.size) * tile_size

	var margin = 100.0

	dungeon_size += Vector2(margin, margin)

	var zoom_x = viewport_size.x / dungeon_size.x
	var zoom_y = viewport_size.y / dungeon_size.y

	var zoom_value = min(zoom_x, zoom_y)

	camera.zoom = Vector2(zoom_value, zoom_value)
