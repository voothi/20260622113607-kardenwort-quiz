-- tsv_quiz.lua
-- A command-line utility to parse vocabulary from a TSV file and run a study quiz.
-- Demonstrates core Lua concepts: File I/O, tables, loops, string parsing, and interactive console input.

-- Shim for unit tests to intercept OS execution/commands
if os.getenv("TEST_COMMAND_LOG") then
	local old_execute = os.execute
	rawset(os, "execute", function(cmd)
		local log_file = os.getenv("TEST_COMMAND_LOG")
		if log_file then
			local f = io.open(log_file, "a")
			if f then
				f:write(cmd .. "\n")
				f:close()
			end
		end
		-- Do not actually run the command during tests to avoid launching processes
		return true, "exit", 0
	end)
end

local print_help
local print_interactive_help
local master_vocab = {}
local active_config = nil

-- Resolve directory of the running script for helper lookups
local _script_dir = (arg[0] or ""):match("(.*[/\\])") or ""
local input_helper = _script_dir .. "input_helper.py"

local function parse_zid_and_lang(filepath)
	local basename = filepath:match("([^/\\]+)$") or filepath
	local zid = basename:match("^(%d{14})")
	local lang = basename:match("%.([%w%-_]+)%.[tT][sS][vV]$")
	if lang then
		lang = lang:gsub("_", "-"):lower()
	end
	return zid, lang
end

-- 1. Helper function to split a string by a delimiter (tab), preserving empty columns
local function split_line(line, delimiter)
	local result = {}
	local from = 1
	local delim_from, delim_to = string.find(line, delimiter, from, true)
	while delim_from do
		table.insert(result, string.sub(line, from, delim_from - 1))
		from = delim_to + 1
		delim_from, delim_to = string.find(line, delimiter, from, true)
	end
	table.insert(result, string.sub(line, from))
	return result
end

-- ANSI VT100 VT100 Escape Color Codes Helper Functions
local function c(code, text)
	return string.format("\27[%sm%s\27[0m", code, text)
end

local function bold(text)
	return c("1", text)
end
local function dim(text)
	return c("90", text)
end
local function cyan(text)
	return c("36", text)
end
local function green(text)
	return c("32", text)
end
local function yellow(text)
	return c("33", text)
end
local function red(text)
	return c("31", text)
end
local function magenta(text)
	return c("35", text)
end
local function light_red(text)
	return c("91", text)
end
local function white(text)
	return c("97", text)
end

-- Map a color name string (from config) to a coloring function.
-- Supported names: red, coral, light_red, yellow, cyan, green, magenta, white, standard
local function get_prompt_color_fn(name)
	name = (name or "standard"):lower()
	if name == "red"      then return red
	elseif name == "coral" or name == "light_red" then return light_red
	elseif name == "yellow"  then return yellow
	elseif name == "cyan"    then return cyan
	elseif name == "green"   then return green
	elseif name == "magenta" then return magenta
	elseif name == "white"   then return white
	else return nil  -- "standard": bold only, no extra color
	end
end

local function invert(text)
	return c("7", text)
end

local function format_wildcard(color_fn, text, blank_inverted_colors, blank_color)
	if color_fn == yellow then
		if blank_color == "standard" then
			color_fn = function(t) return t end
		elseif blank_color == "gray" or blank_color == "grey" then
			color_fn = dim
		end
	end
	if blank_inverted_colors then
		return invert(color_fn(text))
	else
		return bold(color_fn(text))
	end
end

local function get_helper_cmd_prefix(mode)
	local python_bin = "python"
	local extra_args = ""
	if active_config then
		python_bin = active_config.python_cmd or "python"
		if active_config.mpv_integration then
			extra_args = " --mpv-integration"
			if active_config.quiz_pipe_path and active_config.quiz_pipe_path ~= "" then
				extra_args = extra_args .. string.format(' --quiz-pipe-path "%s"', active_config.quiz_pipe_path)
			end
		end
	end
	if python_bin:find(" ") then
		python_bin = '"' .. python_bin .. '"'
	end
	return string.format('%s "%s" %s%s', python_bin, input_helper, mode, extra_args)
end

local function sync_forward_to_mpv(entry, config)
	if not config or not config.mpv_integration then
		print(bold(red("MPV Integration is disabled in config.ini.")))
		return
	end
	local filename = entry.filename
	local timestamp = entry.timestamp or entry.source_index or "0.0"
	local pipe_path = config.mpv_pipe_path
	local python_bin = config.python_cmd or "python"
	
	local extra_play_arg = config.mpv_play_on_sync and " --play" or ""
	local mpv_cmd_arg = config.mpv_cmd and string.format(' --mpv-cmd "%s"', config.mpv_cmd) or ""
	local cmd
	if package.config:sub(1, 1) == "\\" then
		if python_bin:find(" ") then
			python_bin = '"' .. python_bin .. '"'
		end
		cmd = string.format('start "" /b %s "%s" --sync-mpv "%s" "%s" %s%s%s 2>nul', python_bin, input_helper, pipe_path, filename, timestamp, extra_play_arg, mpv_cmd_arg)
	else
		cmd = string.format('"%s" "%s" --sync-mpv "%s" "%s" %s%s%s >/dev/null 2>&1 &', python_bin, input_helper, pipe_path, filename, timestamp, extra_play_arg, mpv_cmd_arg)
	end
	os.execute(cmd)
end

-- UTF-8 Safe string helpers
local function utf8_len(str)
	return utf8.len(str) or #str
end

local function utf8_sub(str, start_char, end_char)
	local len = utf8_len(str)
	start_char = start_char or 1
	end_char = end_char or len

	if start_char < 0 then
		start_char = len + start_char + 1
	end
	if end_char < 0 then
		end_char = len + end_char + 1
	end
	if start_char < 1 then
		start_char = 1
	end
	if end_char > len then
		end_char = len
	end
	if start_char > end_char then
		return ""
	end

	local start_byte = utf8.offset(str, start_char)
	local end_byte
	if end_char == len then
		end_byte = #str
	else
		end_byte = utf8.offset(str, end_char + 1) - 1
	end

	return str:sub(start_byte, end_byte)
end

-- -- Helper to pad columns to target length
local function ensure_columns_len(columns, target_len)
	for i = #columns + 1, target_len do
		columns[i] = ""
	end
	return columns
end

-- Helper to check if a list of columns resembles a TSV header
local function is_header_row(columns, config)
	for _, col in ipairs(columns) do
		local c = col:gsub("%s+$", ""):gsub("^%s+", ""):lower()
		if c == "wordsource" or c == "quotation" or c == "wordsourceinflectedform" or c == "sentencesource" then
			return true
		end
	end
	if config then
		if config.fields then
			for _, f in ipairs(config.fields) do
				local clean_f = f:gsub("%s+$", ""):gsub("^%s+", ""):lower()
				for _, col in ipairs(columns) do
					local c = col:gsub("%s+$", ""):gsub("^%s+", ""):lower()
					if c == clean_f and c ~= "" then
						return true
					end
				end
			end
		end
		for _, mapping in ipairs({ config.fields_mapping_word, config.fields_mapping_sentence }) do
			if mapping then
				for k, _ in pairs(mapping) do
					local clean_k = k:gsub("%s+$", ""):gsub("^%s+", ""):lower()
					for _, col in ipairs(columns) do
						local c = col:gsub("%s+$", ""):gsub("^%s+", ""):lower()
						if c == clean_k and c ~= "" then
							return true
						end
					end
				end
			end
		end
	end
	return false
end

-- Parse human-readable duration (e.g. 5m, 1h, 1d) to seconds
local function parse_duration_to_seconds(duration_str)
	local num, unit = duration_str:match("^(%d+)([smhd]?)$")
	if not num then
		return 0
	end
	local val = tonumber(num)
	if unit == "s" then
		return val
	elseif unit == "m" then
		return val * 60
	elseif unit == "h" then
		return val * 3600
	elseif unit == "d" then
		return val * 86400
	else
		return val
	end
end

local seeded = false
local function shuffle_table(t)
	if not seeded then
		math.randomseed(os.time())
		math.random()
		math.random()
		math.random()
		seeded = true
	end
	for i = #t, 2, -1 do
		local j = math.random(i)
		t[i], t[j] = t[j], t[i]
	end
	return t
end

-- Helper to clear the terminal screen using ANSI escape sequences
local function clear_screen()
	io.write("\27[2J\27[H")
end

-- Helper to wait for a keypress (supporting Space and Enter)
local function press_any_key(prompt, allowed_keys, use_arrows)
	io.write(prompt)
	io.flush()
	while true do
		local key = ""
		if package.config:sub(1, 1) == "\\" then
			local arrow_arg = ""
			if use_arrows == "swap" then
				arrow_arg = " --swap-arrows"
			elseif use_arrows then
				arrow_arg = " --arrows"
			end
			local prefix = get_helper_cmd_prefix("--key")
			local cmd = string.format('%s%s 2>nul', prefix, arrow_arg)
			if cmd:sub(1, 1) == '"' then
				cmd = '"' .. cmd .. '"'
			end
			local f = io.popen(cmd)
			if f then
				key = f:read("*a")
				f:close()
			end
		else
			local f = io.popen("read -n 1 -s -r key; echo -n $key")
			if f then
				key = f:read("*a")
				f:close()
			end
		end

		-- Pytest sends empty string when no tty
		if key == "" then
			return key
		end

		if key:sub(1, 1) == "/" then
			if key ~= "/resize" and not (active_config and active_config.single_card_mode) then
				print()
			end
			return key
		end

		if not allowed_keys then
			if not (active_config and active_config.single_card_mode) then
				print()
			end
			return key
		end

		local lkey = key:lower()
		for _, v in ipairs(allowed_keys) do
			if key == v or lkey == v then
				if key ~= "\x1b" and key ~= "\27" and not (active_config and active_config.single_card_mode) then
					print()
				end
				return key
			end
		end
	end
end

-- Simple INI parser for config.ini
local function load_config(filename)
	local config = {
		intervals = { 300, 3600, 86400, 259200, 604800 }, -- default seconds: 5m, 1h, 1d, 3d, 7d
		new_cards_per_day = 20,
		study_ahead = false,
		incorrect_penalty = "reset",
		new_review_order = "review_first",
		review_sort_order = "due_date",
		new_sort_order = "order_added",
		single_card_mode = false,
		command_mode = false,
		start_in_command_mode = false,
		command_mode_esc_toggles = true,
		command_mode_save_input = false,
		command_mode_save_command = false,
		command_mode_single_key = false,
		arrow_hints = false,
		command_mode_arrow_hints = nil,
		answer_mode_arrow_hints = nil,
		exact_length_mask = false,
		show_hint = true,
		hint_flash_duration = -1,
		typing_preview = false,
		battleship_feedback = false,
		case_sensitive_diff = true,
		ignore_punctuation = true,
		diff_inverted_colors = false,
		blank_inverted_colors = false,
		blank_color = "yellow",
		command_mode_prompt_color = "coral",
		answer_mode_prompt_color = "standard",
		show_diff_with_battleship = true,
		anki_grading = false,
		repeat_counts_in_stats = false,
		mpv_integration = false,
		mpv_play_on_sync = true,
		mpv_cmd = "mpv",
		mpv_pipe_path = package.config:sub(1, 1) == "\\" and "\\\\.\\pipe\\mpv-socket" or "/tmp/mpv-socket",
		quiz_pipe_path = package.config:sub(1, 1) == "\\" and "\\\\.\\pipe\\kardenwort-quiz" or "/tmp/kardenwort-quiz",
		python_cmd = "python",
		fields = {},
		fields_mapping_word = {},
		fields_mapping_sentence = {},
		ordered_fields_word = {},
		ordered_fields_sentence = {},
		settings = {},
	}

	local f = io.open(filename, "r")
	if not f then
		return config
	end

	local current_section = nil
	for line in f:lines() do
		local raw_clean = line:match("^%s*(.-)%s*$")
		local is_comment = raw_clean:match("^#") or raw_clean:match("^;")
		if raw_clean ~= "" and not is_comment then
			local clean = raw_clean:gsub("%s*#.*", ""):gsub("%s*;.*", ""):gsub("^%s+", ""):gsub("%s+$", "")
			local section = clean:match("^%[(.+)%]$")
			if section then
				current_section = section:lower()
			else
				if current_section == "fields" then
					table.insert(config.fields, clean)
				else
					local key, val = clean:match("^%s*([^=]+)%s*=%s*(.-)%s*$")
					if key and val then
						key = key:gsub("^%s+", ""):gsub("%s+$", "")
						val = val:gsub("^%s+", ""):gsub("%s+$", "")
						-- Strip quotes from val if any
						if val:match('^".*"$') or val:match("^'.*'$") then
							val = val:sub(2, -2)
						end

						if current_section == "leitner" then
							if key == "intervals" then
								local list = {}
								for part in val:gmatch("[^,%s]+") do
									local secs = parse_duration_to_seconds(part)
									if secs > 0 then
										table.insert(list, secs)
									end
								end
								if #list > 0 then
									config.intervals = list
								end
							elseif key == "new_cards_per_day" then
								config.new_cards_per_day = tonumber(val) or config.new_cards_per_day
							elseif key == "study_ahead" then
								config.study_ahead = (val == "true" or val == "1")
							elseif key == "incorrect_penalty" then
								val = val:lower()
								if val == "reset" or val == "decrease" then
									config.incorrect_penalty = val
								end
							elseif key == "new_review_order" then
								val = val:lower()
								if val == "review_first" or val == "new_first" or val == "mix" then
									config.new_review_order = val
								end
							elseif key == "review_sort_order" then
								val = val:lower()
								if val == "due_date" or val == "order_added" or val == "random" then
									config.review_sort_order = val
								end
							elseif key == "new_sort_order" then
								val = val:lower()
								if val == "order_added" or val == "random" then
									config.new_sort_order = val
								end
							elseif key == "single_card_mode" then
								config.single_card_mode = (val == "true" or val == "1")
							elseif key == "command_mode" then
								config.command_mode = (val == "true" or val == "1")
							elseif key == "start_in_command_mode" then
								config.start_in_command_mode = (val == "true" or val == "1")
							elseif key == "command_mode_esc_toggles" then
								config.command_mode_esc_toggles = (val == "true" or val == "1")
							elseif key == "command_mode_save_input" then
								config.command_mode_save_input = (val == "true" or val == "1")
							elseif key == "command_mode_save_command" then
								config.command_mode_save_command = (val == "true" or val == "1")
							elseif key == "command_mode_single_key" then
								config.command_mode_single_key = (val == "true" or val == "1")
							elseif key == "arrow_hints" then
								val = val:lower()
								local parsed_hints
								if val == "swap" or val == "reverse" then
									parsed_hints = "swap"
								else
									parsed_hints = (val == "true" or val == "1")
								end
								config.arrow_hints = parsed_hints
							elseif key == "command_mode_arrow_hints" then
								val = val:lower()
								if val == "swap" or val == "reverse" then
									config.command_mode_arrow_hints = "swap"
								else
									config.command_mode_arrow_hints = (val == "true" or val == "1")
								end
							elseif key == "answer_mode_arrow_hints" then
								val = val:lower()
								if val == "swap" or val == "reverse" then
									config.answer_mode_arrow_hints = "swap"
								else
									config.answer_mode_arrow_hints = (val == "true" or val == "1")
								end
							elseif key == "exact_length_mask" then
								config.exact_length_mask = (val == "true" or val == "1")
							elseif key == "show_hint" or key == "show_hints" then
								config.show_hint = (val == "true" or val == "1")
							elseif key == "hint_flash_duration" then
								config.hint_flash_duration = tonumber(val) or config.hint_flash_duration
							elseif key == "typing_preview" then
								config.typing_preview = (val == "true" or val == "1")
							elseif key == "battleship_feedback" then
								config.battleship_feedback = (val == "true" or val == "1")
							elseif key == "case_sensitive_diff" then
								config.case_sensitive_diff = (val == "true" or val == "1")
							elseif key == "ignore_punctuation" then
								config.ignore_punctuation = (val == "true" or val == "1")
							elseif key == "diff_inverted_colors" then
								config.diff_inverted_colors = (val == "true" or val == "1")
							elseif key == "blank_inverted_colors" then
								config.blank_inverted_colors = (val == "true" or val == "1")
							elseif key == "blank_color" then
								config.blank_color = val:lower()
							elseif key == "command_mode_prompt_color" then
								config.command_mode_prompt_color = val:lower()
							elseif key == "answer_mode_prompt_color" then
								config.answer_mode_prompt_color = val:lower()
							elseif key == "show_diff_with_battleship" then
								config.show_diff_with_battleship = (val == "true" or val == "1")
							elseif key == "preview_inverted_colors" then
								-- silently ignore stale key
							elseif key == "anki_grading" then
								config.anki_grading = (val == "true" or val == "1")
							elseif key == "repeat_counts_in_stats" then
								config.repeat_counts_in_stats = (val == "true" or val == "1")
							elseif key == "mpv_integration" then
								config.mpv_integration = (val == "true" or val == "1")
							elseif key == "mpv_play_on_sync" then
								config.mpv_play_on_sync = (val == "true" or val == "1")
							elseif key == "mpv_cmd" then
								config.mpv_cmd = val
							elseif key == "mpv_pipe_path" then
								config.mpv_pipe_path = val
							elseif key == "quiz_pipe_path" then
								config.quiz_pipe_path = val
							elseif key == "python_cmd" then
								config.python_cmd = val
							end
						elseif current_section == "fields_mapping.word" then
							config.fields_mapping_word[key] = val
							table.insert(config.ordered_fields_word, key)
						elseif current_section == "fields_mapping.sentence" then
							config.fields_mapping_sentence[key] = val
							table.insert(config.ordered_fields_sentence, key)
						elseif current_section == "settings" then
							config.settings[key] = val
						end
					end
				end
			end
		elseif raw_clean == "" then
			if current_section == "fields" then
				table.insert(config.fields, "")
			end
		end
	end
	f:close()
	if config.command_mode_arrow_hints == nil then
		config.command_mode_arrow_hints = config.arrow_hints
	end
	if config.answer_mode_arrow_hints == nil then
		config.answer_mode_arrow_hints = config.arrow_hints
	end
	while #config.fields > 0 and config.fields[#config.fields] == "" do
		table.remove(config.fields)
	end
	return config
end

-- Atomic and secure TSV writer
local function save_tsv(filename, raw_rows)
	local tmp_filename = filename .. ".tmp"
	local bak_filename = filename .. ".bak"

	local file, err = io.open(tmp_filename, "w")
	if not file then
		return false, "Could not open temporary file for writing: " .. tostring(err)
	end

	for _, row in ipairs(raw_rows) do
		if row.type == "comment" then
			file:write(row.content .. "\n")
		elseif row.type == "empty" then
			file:write(row.content .. "\n")
		elseif row.type == "header" then
			file:write(table.concat(row.columns, "\t") .. "\n")
		elseif row.type == "data" then
			file:write(table.concat(row.columns, "\t") .. "\n")
		end
	end
	file:close()

	-- Atomic rename logic safe for Windows (since Windows fails on target collision, we use a .bak renaming dance)
	os.remove(bak_filename)
	local ok, rename_err = os.rename(filename, bak_filename)
	if not ok then
		-- Target doesn't exist yet (e.g. creating new file)
		local ok2, rename_err2 = os.rename(tmp_filename, filename)
		if not ok2 then
			return false, "Could not write file: " .. tostring(rename_err2)
		end
		return true
	end

	local ok2, rename_err2 = os.rename(tmp_filename, filename)
	if not ok2 then
		-- Restore backup if tmp rename failed
		os.rename(bak_filename, filename)
		return false, "Could not overwrite file, restored backup: " .. tostring(rename_err2)
	end

	os.remove(bak_filename)
	return true
end

-- Helper to format time differences nicely for users
local function format_time_diff(seconds)
	if seconds <= 0 then
		return "now"
	elseif seconds < 60 then
		return string.format("%d seconds", seconds)
	elseif seconds < 3600 then
		return string.format("%d minutes", math.floor(seconds / 60))
	elseif seconds < 86400 then
		return string.format("%d hours", math.floor(seconds / 3600))
	else
		return string.format("%d days", math.floor(seconds / 86400))
	end
end

-- 2. Function to load data from the TSV file using header mapping
local function load_tsv(filename, config)
	local vocabulary = {}
	local raw_rows = {}

	local invalid_exts = {
		srt = "a subtitle",
		vtt = "a subtitle",
		mp4 = "a video",
		mkv = "a video",
		avi = "a video",
		webm = "a video",
		mov = "a video",
		mp3 = "an audio",
		wav = "an audio",
		m4a = "an audio",
		png = "an image",
		jpg = "an image",
		jpeg = "an image",
		gif = "an image",
	}
	local ext = filename:match("%.([^%.]+)$")
	if ext then
		local file_type = invalid_exts[ext:lower()]
		if file_type then
			return nil,
				nil,
				nil,
				nil,
				string.format("Selected file appears to be %s file (.%s). Please select a vocabulary TSV file instead.", file_type, ext:lower())
		end
	end

	local file, err = io.open(filename, "r")
	if not file then
		return nil, nil, nil, nil, "Could not open file: " .. tostring(err)
	end

	local headers = nil
	local total_lines = 0
	local parsed_rows = 0

	for line in file:lines() do
		total_lines = total_lines + 1
		local clean_line = line:gsub("^%s+", ""):gsub("%s+$", "")
		if clean_line == "" then
			table.insert(raw_rows, { type = "empty", content = line })
		-- Store comment lines directly
		elseif line:sub(1, 1) == "#" then
			table.insert(raw_rows, { type = "comment", content = line })
		elseif not headers then
			-- This is the first non-comment line. Check if it is a header row
			local cols = split_line(line, "\t")
			for idx, val in ipairs(cols) do
				cols[idx] = val:gsub("^%s+", ""):gsub("%s+$", "")
			end
			if is_header_row(cols, config) then
				headers = cols
				table.insert(raw_rows, { type = "header", columns = cols })
			else
				-- Headerless! Generate default headers
				if config and config.fields and #config.fields > 0 then
					headers = {}
					for i, v in ipairs(config.fields) do
						headers[i] = v
					end
				else
					headers = {
						"WordSource",
						"WordSourceInflectedForm",
						"WordSource2",
						"Quotation",
						"WordDestination",
						"SentenceSource",
						"Note",
						"SourceURL",
						"Source-en-GB",
						"Source-en-US",
						"SentenceSourceIndex",
						"Deck",
					}
				end
				table.insert(raw_rows, { type = "header", columns = headers })

				-- Process this first line as a data row
				parsed_rows = parsed_rows + 1
				table.insert(raw_rows, { type = "data", columns = cols })
			end
		else
			-- Already have headers, parse as data row
			local cols = split_line(line, "\t")
			for idx, val in ipairs(cols) do
				cols[idx] = val:gsub("^%s+", ""):gsub("%s+$", "")
			end
			parsed_rows = parsed_rows + 1
			table.insert(raw_rows, { type = "data", columns = cols })
		end
	end
	file:close()

	if total_lines == 0 then
		return nil, nil, nil, nil, "The file is completely empty."
	elseif not headers then
		return nil, nil, nil, nil, "No header row could be resolved."
	end

	-- Make sure box and due headers are in headers
	local box_idx = nil
	local due_idx = nil
	local box_field_name = nil
	local due_field_name = nil

	if config then
		for _, mapping in ipairs({ config.fields_mapping_word, config.fields_mapping_sentence }) do
			if mapping then
				for k, v in pairs(mapping) do
					if v == "leitner_box" and not box_field_name then
						box_field_name = k
					elseif v == "leitner_due" and not due_field_name then
						due_field_name = k
					end
				end
			end
		end
	end

	box_field_name = box_field_name or "LeitnerBox"
	due_field_name = due_field_name or "LeitnerDue"

	for idx, h in ipairs(headers) do
		local clean_header = h:gsub("%s+$", ""):gsub("^%s+", "")
		if clean_header == box_field_name then
			box_idx = idx
		elseif clean_header == due_field_name then
			due_idx = idx
		end
	end

	if not box_idx then
		table.insert(headers, box_field_name)
		box_idx = #headers
	end
	if not due_idx then
		table.insert(headers, due_field_name)
		due_idx = #headers
	end

	-- Map header names to their column indices for target word & context sentence extraction
	local found_cols = {}
	for idx, h in ipairs(headers) do
		local clean_header = h:gsub("%s+$", ""):gsub("^%s+", "")
		found_cols[clean_header] = idx
	end

	-- Compile candidate index mappings for word and sentence profiles
	local target_word_indices = {}
	local context_sentence_indices = {}

	local function add_index_if_unique(list, idx)
		for _, existing in ipairs(list) do
			if existing == idx then
				return
			end
		end
		table.insert(list, idx)
	end

	if config and config.fields_mapping_word and next(config.fields_mapping_word) then
		for _, key in ipairs(config.ordered_fields_word) do
			local val = config.fields_mapping_word[key]
			local idx = found_cols[key]
			if idx then
				if val == "source_word" then
					add_index_if_unique(target_word_indices, idx)
				elseif val == "source_sentence" then
					add_index_if_unique(context_sentence_indices, idx)
				end
			end
		end
	end

	if config and config.fields_mapping_sentence and next(config.fields_mapping_sentence) then
		for _, key in ipairs(config.ordered_fields_sentence) do
			local val = config.fields_mapping_sentence[key]
			local idx = found_cols[key]
			if idx then
				if val == "source_word" then
					add_index_if_unique(target_word_indices, idx)
				elseif val == "source_sentence" then
					add_index_if_unique(context_sentence_indices, idx)
				end
			end
		end
	end

	-- Fallbacks
	if #target_word_indices == 0 then
		local word_candidates = { "WordSource", "WordSourceInflectedForm", "Quotation" }
		for _, name in ipairs(word_candidates) do
			if found_cols[name] then
				table.insert(target_word_indices, found_cols[name])
			end
		end
	end
	if #context_sentence_indices == 0 then
		local sentence_candidates = {
			"SentenceSource",
			"SentenceSourceContextLeft",
			"WordSourceContext",
			"SentenceSourceRewriteAISentenceSource",
			"SentenceGerman",
		}
		for _, name in ipairs(sentence_candidates) do
			if found_cols[name] then
				table.insert(context_sentence_indices, found_cols[name])
			end
		end
	end

	local fallback_word_idx = target_word_indices[1] or 1
	local fallback_sentence_idx = context_sentence_indices[1] or 6

	-- Now parse vocabulary data from raw_rows
	for _, row in ipairs(raw_rows) do
		if row.type == "data" then
			ensure_columns_len(row.columns, #headers)
			local columns = row.columns

			local final_word = nil
			local final_context = nil

			for _, idx in ipairs(target_word_indices) do
				local val = columns[idx]
				if val and val ~= "" then
					final_word = val
					break
				end
			end
			if not final_word or final_word == "" then
				final_word = columns[fallback_word_idx]
			end

			for _, idx in ipairs(context_sentence_indices) do
				local val = columns[idx]
				if val and val ~= "" then
					final_context = val
					break
				end
			end
			if not final_context or final_context == "" then
				final_context = columns[fallback_sentence_idx]
			end

			if final_word and final_word ~= "" and final_context and final_context ~= "" then
				-- Parse Leitner values
				local box_val = tonumber(columns[box_idx]) or 1
				local due_val = tonumber(columns[due_idx]) or 0

				local source_index_idx = found_cols["SentenceSourceIndex"]
				local source_idx_val = nil
				if source_index_idx then
					local raw_idx = columns[source_index_idx]
					if raw_idx and raw_idx ~= "" then
						source_idx_val = raw_idx
					end
				end

				local note_idx = found_cols["Note"]
				local note_val = nil
				if note_idx then
					local raw_note = columns[note_idx]
					if raw_note and raw_note ~= "" then
						note_val = raw_note
					end
				end

				table.insert(vocabulary, {
					word = final_word,
					context = final_context,
					box = box_val,
					due = due_val,
					source_index = source_idx_val,
					timestamp = note_val,
					raw_columns = columns,
				})
			end
		end
	end

	if parsed_rows == 0 then
		return nil,
			nil,
			nil,
			nil,
			"No vocabulary entries found (empty file or headers only)."
	elseif #vocabulary == 0 then
		return nil,
			nil,
			nil,
			nil,
			"No valid vocabulary entries could be loaded (target word and context sentence required)."
	end

	return vocabulary, raw_rows, box_idx, due_idx
end

-- Helper to print the standardized quiz header
local function print_header(config)
	print(bold(cyan("Kardenwort TSV Quiz")))
	print(bold(cyan("-------------------")))
	if config.exact_length_mask then
		print(dim("Fill in the blanks based on the context sentence."))
	else
		print(dim("Fill in the blank '") .. yellow("___") .. dim("' based on the context sentence."))
	end
	print(dim("Type '/q' or '/exit' to quit.\n"))
end

-- Generate placeholder for a given word/phrase based on configuration
local function get_mask_placeholder(word, use_exact)
	if not use_exact then
		return "___"
	end

	local success, result = pcall(function()
		if not utf8 then
			error("No utf8 lib")
		end
		local s = ""
		for _, code in utf8.codes(word) do
			local c = utf8.char(code)
			if c:match("[%p%s]") then
				s = s .. c
			else
				s = s .. "_"
			end
		end
		return s
	end)

	if success then
		return result
	else
		local s = ""
		for i = 1, #word do
			local c = word:sub(i, i)
			if c:match("[%p%s]") then
				s = s .. c
			else
				s = s .. "_"
			end
		end
		return s
	end
end

-- Helper to generate a mask string for a word, optionally revealing specified positions
local function get_hint_masked_word(word, n, k, m)
	local len = utf8_len(word)

	-- Determine range of middle characters to show
	local mid_start, mid_end = 0, 0
	if k > 0 then
		mid_start = math.floor((len - k) / 2) + 1
		mid_end = mid_start + k - 1
	end

	local success, result = pcall(function()
		if not utf8 then
			error("No utf8 lib")
		end
		local s = ""
		local idx = 1
		for _, code in utf8.codes(word) do
			local c = utf8.char(code)
			if c:match("[%p%s]") then
				s = s .. c
			else
				-- Check if this position is revealed
				local is_revealed = false
				if idx <= n then
					is_revealed = true
				elseif idx >= len - m + 1 then
					is_revealed = true
				elseif idx >= mid_start and idx <= mid_end then
					is_revealed = true
				end

				if is_revealed then
					s = s .. c
				else
					s = s .. "_"
				end
			end
			idx = idx + 1
		end
		return s
	end)

	if success then
		return result
	else
		-- Fallback to simple byte-by-byte if invalid UTF-8
		local s = ""
		for i = 1, #word do
			local c = word:sub(i, i)
			if c:match("[%p%s]") then
				s = s .. c
			else
				local is_revealed = false
				if i <= n then
					is_revealed = true
				elseif i >= len - m + 1 then
					is_revealed = true
				elseif i >= mid_start and i <= mid_end then
					is_revealed = true
				end

				if is_revealed then
					s = s .. c
				else
					s = s .. "_"
				end
			end
		end
		return s
	end
end

-- Helper to format hint text with ANSI colors for a single word
local function format_hint_text(word, n, k, m)
	if word:match("^[%p%s]+$") then
		return word
	end
	local len = utf8_len(word)
	local part_start = utf8_sub(word, 1, n)
	local part_end = ""
	if m > 0 then
		part_end = utf8_sub(word, len - m + 1, len)
	end

	if k == 0 then
		if n + m >= len then
			return green(word)
		else
			return green(part_start) .. "..." .. green(part_end)
		end
	else
		local mid_start = math.floor((len - k) / 2) + 1
		local mid_end = mid_start + k - 1
		local part_mid = utf8_sub(word, mid_start, mid_end)

		if n >= mid_start or mid_end >= len - m + 1 or n + k + m >= len then
			return green(word)
		else
			return green(part_start) .. "..." .. green(part_mid) .. "..." .. green(part_end)
		end
	end
end

local function strip_ansi(str)
	return str:gsub("\27%[%d+;?%d*;?%d*m", "")
end

local function get_console_width()
	local cmd = get_helper_cmd_prefix("--width") .. " 2>nul"
	if cmd:sub(1, 1) == '"' then
		cmd = '"' .. cmd .. '"'
	end
	local handle = io.popen(cmd)
	if handle then
		local res = handle:read("*a")
		handle:close()
		local w = tonumber(res)
		if w and w > 20 then
			return w - 1
		end
	end
	return 119
end
-- Default console width fallback (authoritative value is updated per-question in run_quiz)
local console_width = 119

local function tokenize_ansi_utf8(str)
	local tokens = {}
	local i = 1
	local len = #str
	while i <= len do
		-- Note: In Lua, string.find(s, pattern, init) anchors '^' to the 'init' position i,
		-- rather than the absolute beginning of the string, making this anchored match correct.
		local ansi_start, ansi_end = str:find("^\27%[[%d;]*m", i)
		if ansi_start then
			table.insert(tokens, { type = "ansi", val = str:sub(ansi_start, ansi_end) })
			i = ansi_end + 1
		else
			local next_char_idx = utf8.offset(str, 2, i)
			local char_val
			if next_char_idx then
				char_val = str:sub(i, next_char_idx - 1)
				i = next_char_idx
			else
				char_val = str:sub(i)
				i = len + 1
			end
			table.insert(tokens, { type = "char", val = char_val })
		end
	end
	return tokens
end

local function split_word_by_width(word, max_width)
	local tokens = tokenize_ansi_utf8(word)
	local parts = {}
	local current_part = {}
	local current_visible_len = 0
	local active_ansi = {}
	
	for _, tok in ipairs(tokens) do
		if tok.type == "ansi" then
			table.insert(current_part, tok.val)
			if tok.val == "\27[0m" then
				active_ansi = {}
			else
				table.insert(active_ansi, tok.val)
			end
		else
			if current_visible_len >= max_width then
				if #active_ansi > 0 then
					table.insert(current_part, "\27[0m")
				end
				table.insert(parts, table.concat(current_part))
				current_part = {}
				current_visible_len = 0
				for _, ansi_val in ipairs(active_ansi) do
					table.insert(current_part, ansi_val)
				end
			end
			table.insert(current_part, tok.val)
			current_visible_len = current_visible_len + 1
		end
	end
	if #current_part > 0 then
		table.insert(parts, table.concat(current_part))
	end
	return parts
end

local function wrap_text(text, max_width)
	max_width = max_width or console_width
	local lines = {}
	for line in string.gmatch(text .. "\n", "(.-)\n") do
		if line == "" then
			table.insert(lines, "")
		else
			local current_line = ""
			local current_len = 0
			for word, space in line:gmatch("(%S*)(%s*)") do
				if word ~= "" or space ~= "" then
					local word_len = utf8_len(strip_ansi(word))
					local space_len = utf8_len(strip_ansi(space))
					
					if word_len > max_width then
						if current_len > 0 then
							table.insert(lines, (current_line:gsub("%s+$", "")))
							current_line = ""
							current_len = 0
						end
						local word_parts = split_word_by_width(word, max_width)
						for idx = 1, #word_parts - 1 do
							table.insert(lines, word_parts[idx])
						end
						local last_part = word_parts[#word_parts]
						current_line = last_part .. space
						current_len = utf8_len(strip_ansi(last_part)) + space_len
					else
						if current_len > 0 and current_len + word_len > max_width then
							table.insert(lines, (current_line:gsub("%s+$", "")))
							current_line = word .. space
							current_len = word_len + space_len
						else
							current_line = current_line .. word .. space
							current_len = current_len + word_len + space_len
						end
					end
				end
			end
			if current_line ~= "" then
				table.insert(lines, (current_line:gsub("%s+$", "")))
			end
		end
	end
	if lines[#lines] == "" then
		table.remove(lines)
	end
	return table.concat(lines, "\n")
end

local function print_framed_diff(u_line, t_line)
	local raw_u = strip_ansi(u_line)
	local raw_t = strip_ansi(t_line)
	local prefix_u = "User:   "
	local prefix_t = "Target: "
	local len_u = utf8_len(raw_u) + utf8_len(prefix_u)
	local len_t = utf8_len(raw_t) + utf8_len(prefix_t)
	local content_len = math.max(len_u, len_t)
	local box_inner_width = math.max(46, content_len + 4) -- ensures at least 2 spaces pad on each side

	local title = " Diff "
	local top_bar = "╭─" .. title .. string.rep("─", box_inner_width - utf8_len(title) - 1) .. "╮"
	local bot_bar = "╰" .. string.rep("─", box_inner_width) .. "╯"

	print(dim(top_bar))

	local pad_total_u = box_inner_width - len_u
	local pad_left_u = string.rep(" ", math.floor(pad_total_u / 2))
	local pad_right_u = string.rep(" ", math.ceil(pad_total_u / 2))
	print(dim("│") .. pad_left_u .. dim(prefix_u) .. u_line .. pad_right_u .. dim("│"))

	local pad_total_t = box_inner_width - len_t
	local pad_left_t = string.rep(" ", math.floor(pad_total_t / 2))
	local pad_right_t = string.rep(" ", math.ceil(pad_total_t / 2))
	print(dim("│") .. pad_left_t .. dim(prefix_t) .. t_line .. pad_right_t .. dim("│"))

	print(dim(bot_bar))
end

-- Heuristic traceback to prefer contiguous matches in the LCS grid
local function traceback_lcs(dp, A, B, case_sensitive)
	local i = #A
	local j = #B
	local ops = {}
	local last_op = nil

	while i > 0 or j > 0 do
		local match
		if case_sensitive then
			match = (i > 0 and j > 0 and A[i] == B[j])
		else
			match = (i > 0 and j > 0 and A[i]:lower() == B[j]:lower())
		end

		local cost = match and 0 or 1
		local can_match = i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + cost
		local can_missing = j > 0 and dp[i][j] == dp[i][j - 1] + 1
		local can_extra = i > 0 and dp[i][j] == dp[i - 1][j] + 1

		local op_type
		if can_match and cost == 0 then
			if last_op == "match" or (not can_missing and not can_extra) then
				op_type = "match"
			elseif last_op == "missing" and can_missing then
				op_type = "missing"
			elseif last_op == "extra" and can_extra then
				op_type = "extra"
			elseif can_missing then
				op_type = "missing"
			else
				op_type = "extra"
			end
		else
			if can_missing and can_extra then
				if last_op == "missing" then
					op_type = "missing"
				elseif last_op == "extra" then
					op_type = "extra"
				else
					op_type = "missing"
				end
			elseif can_missing then
				op_type = "missing"
			elseif can_extra then
				op_type = "extra"
			else
				op_type = "replace"
			end
		end

		if op_type == "match" then
			table.insert(ops, { type = "match", charA = A[i], charB = B[j] })
			i, j = i - 1, j - 1
		elseif op_type == "missing" then
			table.insert(ops, { type = "missing", charA = "-", charB = B[j] })
			j = j - 1
		elseif op_type == "extra" then
			table.insert(ops, { type = "extra", charA = A[i], charB = "-" })
			i = i - 1
		elseif op_type == "replace" then
			table.insert(ops, { type = "replace", charA = A[i], charB = B[j] })
			i, j = i - 1, j - 1
		end
		last_op = op_type
	end
	return ops
end

-- Helper to perform character-by-character diff (LCS-based) between user input and target word, returning two aligned lines
local function get_two_line_diff(user_str, target_str, case_sensitive, ignore_punctuation, inverted_colors)
	local function clean_for_diff(str)
		local cleaned = str
		if ignore_punctuation then
			cleaned = cleaned:gsub("%p+", "")
		end
		cleaned = cleaned:gsub("%s+", " ")
		cleaned = cleaned:gsub("^%s+", ""):gsub("%s+$", "")
		return cleaned
	end

	local clean_user = clean_for_diff(user_str)
	local clean_target = clean_for_diff(target_str)

	local function to_chars(str)
		local ok, chars = pcall(function()
			local c = {}
			for _, code in utf8.codes(str) do
				table.insert(c, utf8.char(code))
			end
			return c
		end)
		if ok then
			return chars
		end
		local chars = {}
		for i = 1, #str do
			table.insert(chars, str:sub(i, i))
		end
		return chars
	end

	local A = to_chars(clean_user)
	local B = to_chars(clean_target)
	local n = #A
	local m = #B

	local dp = {}
	for i = 0, n do
		dp[i] = {}
		for j = 0, m do
			dp[i][j] = 0
		end
	end

	for i = 1, n do
		dp[i][0] = i
	end
	for j = 1, m do
		dp[0][j] = j
	end

	for i = 1, n do
		for j = 1, m do
			local cost
			if case_sensitive then
				cost = (A[i] == B[j]) and 0 or 1
			else
				cost = (A[i]:lower() == B[j]:lower()) and 0 or 1
			end
			dp[i][j] = math.min(
				dp[i - 1][j] + 1, -- deletion (extra in user)
				dp[i][j - 1] + 1, -- insertion (missing in user)
				dp[i - 1][j - 1] + cost -- match or substitution
			)
		end
	end

	local ops = traceback_lcs(dp, A, B, case_sensitive)

	local user_parts = {}
	local target_parts = {}

	local function format_char(color_fn, char)
		if inverted_colors then
			return color_fn(invert(char))
		else
			return color_fn(char)
		end
	end

	for k = #ops, 1, -1 do
		local op = ops[k]
		if op.type == "match" then
			table.insert(user_parts, format_char(green, op.charA))
			table.insert(target_parts, format_char(green, op.charB))
		elseif op.type == "replace" then
			table.insert(user_parts, format_char(red, op.charA))
			table.insert(target_parts, format_char(dim, op.charB))
		elseif op.type == "missing" then
			table.insert(user_parts, format_char(dim, op.charA))
			table.insert(target_parts, format_char(dim, op.charB))
		elseif op.type == "extra" then
			table.insert(user_parts, format_char(red, op.charA))
			table.insert(target_parts, format_char(dim, op.charB))
		end
	end

	return table.concat(user_parts, ""), table.concat(target_parts, "")
end

local function get_inline_colored_diff(user_str, original_target, case_sensitive, ignore_punctuation, inverted_colors)
	local function to_chars(str)
		local ok, chars = pcall(function()
			local c = {}
			for _, code in utf8.codes(str) do
				table.insert(c, utf8.char(code))
			end
			return c
		end)
		if ok then
			return chars
		end
		local chars = {}
		for i = 1, #str do
			table.insert(chars, str:sub(i, i))
		end
		return chars
	end

	local user_clean = user_str
	local target_clean = original_target
	if ignore_punctuation then
		user_clean = user_clean:gsub("[%p%s]+", "")
		target_clean = target_clean:gsub("[%p%s]+", "")
	else
		user_clean = user_clean:gsub("%s+", "")
		target_clean = target_clean:gsub("%s+", "")
	end

	if target_clean == "" then
		return original_target
	end

	local A = to_chars(user_clean)
	local B = to_chars(target_clean)
	local n = #A
	local m = #B

	local dp = {}
	for i = 0, n do
		dp[i] = {}
		for j = 0, m do
			dp[i][j] = 0
		end
	end
	for i = 1, n do
		dp[i][0] = i
	end
	for j = 1, m do
		dp[0][j] = j
	end

	for i = 1, n do
		for j = 1, m do
			local cost
			if case_sensitive then
				cost = (A[i] == B[j]) and 0 or 1
			else
				cost = (A[i]:lower() == B[j]:lower()) and 0 or 1
			end
			dp[i][j] = math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
		end
	end

	local ops = traceback_lcs(dp, A, B, case_sensitive)

	local tags = {}
	for k = #ops, 1, -1 do
		if ops[k].type ~= "extra" then
			table.insert(tags, ops[k].type)
		end
	end

	local function format_char(color_fn, ch)
		if inverted_colors then
			return invert(color_fn(ch))
		else
			return bold(color_fn(ch))
		end
	end

	local res = {}
	local tag_idx = 1
	local orig_chars = to_chars(original_target)
	for _, ch in ipairs(orig_chars) do
		if ch:match("[%p%s]") then
			table.insert(res, format_char(green, ch))
		else
			local tag = tags[tag_idx] or "missing"
			tag_idx = tag_idx + 1
			if tag == "match" then
				table.insert(res, format_char(green, ch))
			else
				table.insert(res, format_char(red, ch))
			end
		end
	end
	return table.concat(res, "")
end

-- Replace the target word in the context sentence with a blank line (or exact length blank)
-- Also handles displaying the inline diff if the user's answer is incorrect.
local function mask_context(
	context,
	target_word,
	use_exact,
	has_hint,
	hint_n,
	hint_k,
	hint_m,
	is_correct,
	user_input,
	case_sensitive_diff,
	ignore_punctuation,
	source_index,
	preview_format,
	blank_inverted_colors,
	blank_color
)
	local p1, p2 = target_word:match("^(.-)%s*%.%.%.%s*(.-)$")

	local original_format_wildcard = format_wildcard
	local function format_wildcard(color_fn, text, blank_inverted_colors_param)
		return original_format_wildcard(color_fn, text, blank_inverted_colors_param, blank_color)
	end

	local function escape_pattern(text)
		return text:gsub("([^%w])", "%%%1")
	end

	local function parse_coordinates(coords_str)
		if not coords_str or coords_str == "" then
			return nil
		end
		local coords = {}
		for part in tostring(coords_str):gmatch("[^,]+") do
			local line, word, term_pos = part:match("^(%d+):(%d+):(%d+)$")
			if line and word and term_pos then
				table.insert(coords, {
					line = tonumber(line),
					word = tonumber(word),
					term_pos = tonumber(term_pos),
				})
			else
				local num = tonumber(part)
				if num then
					table.insert(coords, {
						line = 0,
						word = num,
						term_pos = #coords + 1,
					})
				end
			end
		end
		if #coords == 0 then
			return nil
		end
		return coords
	end

	local coords = parse_coordinates(source_index)

	local function get_coords_error(matches_logical_indices)
		if not coords or #coords == 0 then
			return 0
		end
		local n = #coords
		local w_indices = {}
		for idx = 1, n do
			w_indices[idx] = matches_logical_indices[idx] or matches_logical_indices[#matches_logical_indices] or 0
		end

		local line_starts = {}
		for idx = 1, n do
			local c = coords[idx]
			local w_val = w_indices[idx]
			if not line_starts[c.line] then
				line_starts[c.line] = w_val - c.word + 1
			end
		end

		local total_error = 0

		for idx = 1, n do
			local c = coords[idx]
			local w_val = w_indices[idx]
			local est_start = line_starts[c.line]
			local expected_w = est_start + c.word - 1
			total_error = total_error + math.abs(w_val - expected_w)
			total_error = total_error + math.abs(w_val - c.word) * 0.1
		end

		local unique_lines = {}
		for l, _ in pairs(line_starts) do
			table.insert(unique_lines, l)
		end
		table.sort(unique_lines)

		for idx = 1, #unique_lines - 1 do
			local l1 = unique_lines[idx]
			local l2 = unique_lines[idx + 1]
			local s1 = line_starts[l1]
			local s2 = line_starts[l2]
			if s2 <= s1 then
				total_error = total_error + (s1 - s2 + 1) * 10
			end
		end

		for idx = 1, n - 1 do
			local c1 = coords[idx]
			local c2 = coords[idx + 1]
			if c2.line == c1.line + 1 and c2.term_pos == c1.term_pos + 1 then
				local w1 = w_indices[idx]
				local w2 = w_indices[idx + 1]
				total_error = total_error + math.abs(w2 - w1 - 1) * 5
			end
		end

		if n == 1 then
			local c = coords[1]
			local w_val = w_indices[1]
			total_error = total_error + math.abs(w_val - c.word)
		end

		return total_error
	end

	local function is_word_char(c)
		if not c or c == "" then return false end
		local b = string.byte(c)
		if b >= 128 then return true end
		if c:match("%w") then return true end
		return false
	end

	local function get_char_word_indices(text)
		local indices = {}
		local current_word_index = 0
		local in_word = false

		local i = 1
		while i <= #text do
			if text:sub(i, i) == "{" then
				local close_idx = text:find("}", i, true)
				if close_idx then
					for j = i, close_idx do
						indices[j] = 0
					end
					i = close_idx + 1
				else
					indices[i] = 0
					i = i + 1
				end
			else
				local c = text:sub(i, i)
				local is_word_char_val = is_word_char(c)

				if is_word_char_val then
					if not in_word then
						current_word_index = current_word_index + 1
						in_word = true
					end
					indices[i] = current_word_index
					i = i + 1
				else
					in_word = false
					indices[i] = 0
					i = i + 1
				end
			end
		end
		return indices
	end

	local char_word_indices = get_char_word_indices(context)

	local function find_all_occurrences(ctx, word_case, check_word_indices)
		local occurrences = {}
		local e_word = escape_pattern(word_case)
		local pat = "()(" .. e_word .. ")()"
		local last_pos = 1
		while true do
			local start_pos, m, end_pos = ctx:match(pat, last_pos)
			if not start_pos then
				break
			end

			local valid_boundary = true
			local prev_char = ctx:sub(start_pos - 1, start_pos - 1)
			local next_char = ctx:sub(end_pos, end_pos)
			if is_word_char(prev_char) or is_word_char(next_char) then
				valid_boundary = false
			end

			if valid_boundary then
				local w_idx_list = {}
				if check_word_indices then
					local last_w_idx = 0
					for i = start_pos, end_pos - 1 do
						local w_idx = char_word_indices[i] or 0
						if w_idx > 0 and w_idx ~= last_w_idx then
							table.insert(w_idx_list, w_idx)
							last_w_idx = w_idx
						end
					end
				end

				table.insert(occurrences, {
					start_pos = start_pos,
					end_pos = end_pos,
					m = m,
					w_idx_list = w_idx_list,
				})
			end
			last_pos = start_pos + 1
		end
		return occurrences
	end

	if p1 and p2 then
		local r1, r2
		if is_correct ~= nil then
			if is_correct then
				r1 = format_wildcard(green, p1, blank_inverted_colors)
				r2 = format_wildcard(green, p2, blank_inverted_colors)
			else
				local user_p1, user_p2 = "", ""
				if user_input then
					local u_parts = {}
					for part in user_input:gmatch("[^%s]+") do
						table.insert(u_parts, part)
					end
					if #u_parts >= 2 then
						user_p1 = u_parts[1]
						local rest = {}
						for idx = 2, #u_parts do
							table.insert(rest, u_parts[idx])
						end
						user_p2 = table.concat(rest, " ")
					elseif #u_parts == 1 then
						user_p1 = u_parts[1]
					end
				end
				r1 = get_inline_colored_diff(user_p1, p1, case_sensitive_diff, ignore_punctuation, blank_inverted_colors)
				r2 = get_inline_colored_diff(user_p2, p2, case_sensitive_diff, ignore_punctuation, blank_inverted_colors)
			end
		elseif preview_format then
			r1 = "[[TARGET:" .. p1 .. "]]"
			r2 = "[[TARGET:" .. p2 .. "]]"
		elseif has_hint and use_exact then
			local hp1 = get_hint_masked_word(p1, hint_n, hint_k, hint_m)
			local hp2 = get_hint_masked_word(p2, hint_n, hint_k, hint_m)
			r1 = format_wildcard(yellow, hp1, blank_inverted_colors)
			r2 = format_wildcard(yellow, hp2, blank_inverted_colors)
		else
			local mask1 = get_mask_placeholder(p1, use_exact)
			local mask2 = get_mask_placeholder(p2, use_exact)
			r1 = format_wildcard(yellow, mask1, blank_inverted_colors)
			r2 = format_wildcard(yellow, mask2, blank_inverted_colors)
		end

		local function try_replace(p1_case, p2_case)
			local occ1 = find_all_occurrences(context, p1_case, true)
			local occ2 = find_all_occurrences(context, p2_case, true)

			local matches = {}
			for _, o1 in ipairs(occ1) do
				for _, o2 in ipairs(occ2) do
					if o1.start_pos < o2.start_pos then
						local combined_w_indices = {}
						for _, w in ipairs(o1.w_idx_list) do
							table.insert(combined_w_indices, w)
						end
						for _, w in ipairs(o2.w_idx_list) do
							table.insert(combined_w_indices, w)
						end

						table.insert(matches, {
							start_pos = o1.start_pos,
							m1 = o1.m,
							mid = context:sub(o1.end_pos, o2.start_pos - 1),
							m2 = o2.m,
							end_pos = o2.end_pos,
							w_indices = combined_w_indices,
						})
					end
				end
			end

			if #matches == 0 then
				return context, false
			end

			if not coords then
				local non_overlapping = {}
				local last_end = 0
				for _, match in ipairs(matches) do
					if match.start_pos >= last_end then
						table.insert(non_overlapping, match)
						last_end = match.end_pos
					end
				end
				table.sort(non_overlapping, function(a, b) return a.start_pos > b.start_pos end)
				local replaced = context
				for _, match in ipairs(non_overlapping) do
					local final_r1 = r1
					local final_r2 = r2
					if is_correct ~= nil then
						if is_correct then
							final_r1 = format_wildcard(green, match.m1, blank_inverted_colors)
							final_r2 = format_wildcard(green, match.m2, blank_inverted_colors)
						else
							final_r1 = r1
							final_r2 = r2
						end
					end
					replaced = replaced:sub(1, match.start_pos - 1)
						.. final_r1
						.. match.mid
						.. final_r2
						.. replaced:sub(match.end_pos)
				end
				return replaced, true
			else
				local best_match = nil
				local min_error = math.huge
				for _, match in ipairs(matches) do
					local err_val = get_coords_error(match.w_indices)
					if err_val < min_error then
						min_error = err_val
						best_match = match
					end
				end

				if not best_match then
					return context, false
				end

				local final_r1 = r1
				local final_r2 = r2
				if is_correct ~= nil then
					if is_correct then
						final_r1 = format_wildcard(green, best_match.m1, blank_inverted_colors)
						final_r2 = format_wildcard(green, best_match.m2, blank_inverted_colors)
					else
						final_r1 = r1
						final_r2 = r2
					end
				end

				local replaced = context:sub(1, best_match.start_pos - 1)
					.. final_r1
					.. best_match.mid
					.. final_r2
					.. context:sub(best_match.end_pos)
				return replaced, true
			end
		end

		local res, replaced = try_replace(p1, p2)
		if replaced then return res end

		res, replaced = try_replace(p1:lower(), p2:lower())
		if replaced then return res end

		local first = utf8_sub(p1, 1, 1):upper()
		local rest = utf8_sub(p1, 2)
		res, replaced = try_replace(first .. rest, p2:lower())
		if replaced then return res end

		return context
	else
		local parts = {}
		for part in target_word:gmatch("[^%s]+") do
			table.insert(parts, part)
		end

		local rep_parts = {}
		for _, part in ipairs(parts) do
			if preview_format then
				table.insert(rep_parts, "[[TARGET:" .. part .. "]]")
			elseif is_correct then
				table.insert(rep_parts, format_wildcard(green, part, blank_inverted_colors))
			elseif has_hint and use_exact then
				table.insert(rep_parts, format_wildcard(yellow, get_hint_masked_word(part, hint_n, hint_k, hint_m), blank_inverted_colors))
			else
				table.insert(rep_parts, format_wildcard(yellow, get_mask_placeholder(part, use_exact), blank_inverted_colors))
			end
		end
		local replacement = table.concat(rep_parts, " ")

		local function try_single_replace(word_case)
			local matches = find_all_occurrences(context, word_case, true)
			if #matches == 0 then return false end

			if coords then
				local best_match = nil
				local min_error = math.huge
				for _, match in ipairs(matches) do
					local err_val = get_coords_error(match.w_idx_list)
					if err_val < min_error then
						min_error = err_val
						best_match = match
					end
				end

				if not best_match then return false end
				matches = { best_match }
			end

			table.sort(matches, function(a, b) return a.start_pos > b.start_pos end)
			local replaced = context
			for _, match in ipairs(matches) do
				local rep
				if is_correct ~= nil then
					if is_correct then
						local m_parts = {}
						for part in match.m:gmatch("[^%s]+") do
							table.insert(m_parts, part)
						end
						local m_rep_parts = {}
						for _, part in ipairs(m_parts) do
							table.insert(m_rep_parts, format_wildcard(green, part, blank_inverted_colors))
						end
						rep = table.concat(m_rep_parts, " ")
					else
						rep = get_inline_colored_diff(user_input or "", match.m, case_sensitive_diff, ignore_punctuation, blank_inverted_colors)
					end
				else
					rep = replacement
				end
				replaced = replaced:sub(1, match.start_pos - 1) .. rep .. replaced:sub(match.end_pos)
			end
			return replaced
		end

		local replaced_ctx = try_single_replace(target_word)
		if replaced_ctx then return replaced_ctx end

		replaced_ctx = try_single_replace(target_word:lower())
		if replaced_ctx then return replaced_ctx end

		local first = utf8_sub(target_word, 1, 1):upper()
		local rest = utf8_sub(target_word, 2)
		replaced_ctx = try_single_replace(first .. rest)
		if replaced_ctx then return replaced_ctx end

		-- Fallback to individual word highlighting
		local sorted_parts = {}
		for _, p in ipairs(parts) do table.insert(sorted_parts, p) end
		table.sort(sorted_parts, function(a, b) return utf8_len(a) > utf8_len(b) end)

		local all_matches = {}
		for _, part in ipairs(sorted_parts) do
			local function collect_word_occurrences(word_case)
				local matches = find_all_occurrences(context, word_case, false)
				if #matches > 0 then
					for _, match in ipairs(matches) do
						table.insert(all_matches, match)
					end
					return true
				end
				return false
			end

			local found = collect_word_occurrences(part)
			if not found then
				found = collect_word_occurrences(part:lower())
				if not found then
					local w_first = utf8_sub(part, 1, 1):upper()
					local w_rest = utf8_sub(part, 2)
					collect_word_occurrences(w_first .. w_rest)
				end
			end
		end

		if #all_matches == 0 then return context end

		table.sort(all_matches, function(a, b)
			if a.start_pos == b.start_pos then
				return a.end_pos > b.end_pos
			end
			return a.start_pos < b.start_pos
		end)

		local non_overlapping = {}
		local last_end = 0
		for _, match in ipairs(all_matches) do
			if match.start_pos >= last_end then
				table.insert(non_overlapping, match)
				last_end = match.end_pos
			end
		end

		table.sort(non_overlapping, function(a, b) return a.start_pos > b.start_pos end)
		local fallback_context = context
		for _, match in ipairs(non_overlapping) do
			local rep
			if preview_format then
				rep = "[[TARGET:" .. match.m .. "]]"
			elseif is_correct ~= nil then
				if is_correct then
					rep = format_wildcard(green, match.m, blank_inverted_colors)
				else
					rep = get_inline_colored_diff(user_input or "", match.m, case_sensitive_diff, ignore_punctuation, blank_inverted_colors)
				end
			else
				if has_hint and use_exact then
					rep = format_wildcard(yellow, get_hint_masked_word(match.m, hint_n, hint_k, hint_m), blank_inverted_colors)
				else
					rep = format_wildcard(yellow, get_mask_placeholder(match.m, use_exact), blank_inverted_colors)
				end
			end
			fallback_context = fallback_context:sub(1, match.start_pos - 1) .. rep .. fallback_context:sub(match.end_pos)
		end

		return fallback_context
	end
end



local function update_and_save_progress(entry, is_correct, config)
	if entry.is_repeat and not config.repeat_counts_in_stats then
		return true, nil
	end

	local now = os.time()
	local new_box = entry.box

	if is_correct then
		new_box = math.min(entry.box + 1, #config.intervals)
	else
		if config.incorrect_penalty == "reset" then
			new_box = 1
		else
			new_box = math.max(1, entry.box - 1)
		end
	end

	local interval = config.intervals[new_box]
	local new_due = now + interval

	-- Save state
	entry.box = new_box
	entry.due = new_due
	entry.raw_columns[entry.box_idx] = tostring(new_box)
	entry.raw_columns[entry.due_idx] = tostring(new_due)

	if config.repeat_counts_in_stats and entry.original_card then
		entry.original_card.box = new_box
		entry.original_card.due = new_due
		if entry.original_card.raw_columns then
			local orig_box_idx = entry.original_card.box_idx or entry.box_idx
			local orig_due_idx = entry.original_card.due_idx or entry.due_idx
			entry.original_card.raw_columns[orig_box_idx] = tostring(new_box)
			entry.original_card.raw_columns[orig_due_idx] = tostring(new_due)
		end
	end

	return save_tsv(entry.filename, entry.raw_rows)
end

local function to_hex(str)
	return (str:gsub('.', function(c)
		return string.format('%02x', string.byte(c))
	end))
end

local function json_encode(val)
	if type(val) == "boolean" then
		return val and "true" or "false"
	elseif type(val) == "number" then
		return tostring(val)
	elseif type(val) == "string" then
		local escaped = val:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t"):gsub("\x1b", "\\u001b")
		return '"' .. escaped .. '"'
	elseif type(val) == "table" then
		local is_array = true
		local count = 0
		local max_key = 0
		for k, _ in pairs(val) do
			if type(k) ~= "number" or k < 1 or math.floor(k) ~= k then
				is_array = false
				break
			end
			if k > max_key then max_key = k end
			count = count + 1
		end
		if is_array and max_key ~= count then
			is_array = false
		end
		if is_array then
			local parts = {}
			for i = 1, count do
				table.insert(parts, json_encode(val[i]))
			end
			return "[" .. table.concat(parts, ",") .. "]"
		else
			local parts = {}
			for k, v in pairs(val) do
				local key_str = tostring(k)
				local escaped_key = key_str:gsub("\\", "\\\\"):gsub('"', '\\"')
				table.insert(parts, '"' .. escaped_key .. '":' .. json_encode(v))
			end
			return "{" .. table.concat(parts, ",") .. "}"
		end
	else
		return "null"
	end
end

local function get_card_header(config, question_num, total, entry)
	local lines = {}
	table.insert(lines, bold(cyan("Kardenwort TSV Quiz")))
	table.insert(lines, bold(cyan("-------------------")))
	if config.exact_length_mask then
		table.insert(lines, dim("Fill in the blanks based on the context sentence."))
	else
		table.insert(lines, dim("Fill in the blank '") .. yellow("___") .. dim("' based on the context sentence."))
	end
	table.insert(lines, dim("Type '/q' or '/exit' to quit.\n"))

	local basename = entry.filename:match("([^/\\]+)$") or entry.filename
	if entry.is_repeat and not config.repeat_counts_in_stats then
		local header_prefix
		if entry.original_question_num then
			header_prefix = string.format("Practice Repeat %d/%d:", entry.original_question_num, total)
		else
			header_prefix = "Practice Repeat (Sync):"
		end
		table.insert(lines, bold(cyan(header_prefix)) .. dim(string.format(" [File: %s | Box %d]", basename, entry.box)))
	else
		local cycle = math.ceil(question_num / total)
		local disp_num = ((question_num - 1) % total) + 1
		local cycle_str = cycle > 1 and string.format(" (Cycle %d)", cycle) or ""
		local repeat_str = entry.is_repeat and " (Repeat)" or ""
		table.insert(
			lines,
			bold(cyan(string.format("Question %d/%d%s%s:", disp_num, total, cycle_str, repeat_str)))
				.. dim(string.format(" [File: %s | Box %d]", basename, entry.box))
		)
	end
	return table.concat(lines, "\n") .. "\n"
end

-- Read a line of input, intercepting Esc (skip) and Ctrl+C (quit) on Windows
local function read_line_with_esc(config, initial_text, save_esc, use_arrows, preview_data)
	io.flush()
	if package.config:sub(1, 1) == "\\" then
		local arrow_arg = ""
		if use_arrows == "swap" then
			arrow_arg = " --swap-arrows"
		elseif use_arrows then
			arrow_arg = " --arrows"
		end
		local save_esc_arg = save_esc and " --save-esc" or ""
		local initial_arg = ""
		if initial_text and initial_text ~= "" then
			local escaped_initial = initial_text:gsub('"', '\\"')
			initial_arg = string.format(' --initial "%s"', escaped_initial)
		end
		local preview_arg = ""
		if preview_data and preview_data ~= "" then
			preview_arg = string.format(' --preview-data "%s"', preview_data)
		end
		local prefix = get_helper_cmd_prefix("--line")
		local cmd = string.format('%s%s%s%s%s 2>nul', prefix, arrow_arg, save_esc_arg, initial_arg, preview_arg)
		if cmd:sub(1, 1) == '"' then
			cmd = '"' .. cmd .. '"'
		end
		local f = io.popen(cmd)
		if f then
			local res = f:read("*a")
			f:close()
			if res ~= "NOT_TTY" then
				if res:sub(1, 1) ~= "\27" and not config.single_card_mode then
					print() -- move to next line after input
				end
				return res -- return even if empty (empty Enter = empty answer)
			end
		end
	end
	if preview_data and preview_data ~= "" and package.config:sub(1, 1) == "\\" then
		local _ans_color_fn = active_config and get_prompt_color_fn(active_config.answer_mode_prompt_color) or nil
		io.write(bold(_ans_color_fn and _ans_color_fn("Answer") or "Answer") .. dim(" (type '/?' for help): "))
	end
	local val = io.read()
	if val == "" and initial_text and initial_text ~= "" then
		return initial_text
	end
	return val
end

-- 3. Run the interactive CLI quiz
-- Helper to create a repeat entry copy.
-- NOTE: fields like raw_columns and raw_rows are intentionally shared by reference with the original card
-- to support in-memory progress synchronization (spaced repetition boxes/due dates) back to the master list.
local function make_repeat_entry(target_card, target_idx, study_queue)
	local repeat_entry = {}
	for k, v in pairs(target_card) do
		repeat_entry[k] = v
	end
	repeat_entry.is_repeat = true
	repeat_entry.repeat_target_idx = target_idx
	repeat_entry.original_card = target_card.original_card or target_card

	if target_card.is_repeat then
		repeat_entry.original_question_num = target_card.original_question_num
	elseif study_queue then
		local count = 0
		for idx = 1, target_idx do
			local card = study_queue[idx]
			if card and not card.is_repeat then
				count = count + 1
			end
		end
		repeat_entry.original_question_num = count
	else
		repeat_entry.original_question_num = 1
	end
	return repeat_entry
end

local function run_quiz(study_queue, config, start_sync_zid, start_sync_time)
	if not study_queue then
		study_queue = {}
	end

	if start_sync_zid and start_sync_time then
		local best_entry = nil
		local min_diff = math.huge
		for _, e in ipairs(master_vocab) do
			local e_filename = e.filename:match("([^/\\]+)$") or e.filename
			if e_filename:find(start_sync_zid, 1, true) then
				local e_time = tonumber(e.timestamp) or tonumber(e.source_index) or 0.0
				local diff = math.abs(e_time - start_sync_time)
				if diff < min_diff then
					min_diff = diff
					best_entry = e
				end
			end
		end

		if best_entry then
			local sync_entry = {}
			for k, v in pairs(best_entry) do
				sync_entry[k] = v
			end
			sync_entry.is_repeat = true
			sync_entry.original_card = best_entry
			table.insert(study_queue, 1, sync_entry)
		end
	end

	if #study_queue == 0 then
		print("No cards to review.")
		return
	end

	local score = 0
	local total = #study_queue
	local question_num = 0

	for i, entry in ipairs(study_queue) do
		console_width = get_console_width()
		if entry.original_card then
			entry.box = entry.original_card.box
			entry.due = entry.original_card.due
		end
		if not entry.is_repeat then
			question_num = question_num + 1
		end
		local target_word = entry.word
		local current_hint = nil
		local hint_n, hint_k, hint_m = 0, 0, 0
		local has_hint = false

		local is_command_mode = config.start_in_command_mode and config.command_mode
		local saved_input = ""
		local saved_command_input = ""
		local redraw_needed = true
		local skip_input_read = false

		local function defer_current_card()
			local deferred_entry = {}
			for k, v in pairs(entry) do
				deferred_entry[k] = v
			end
			deferred_entry.original_card = entry.original_card or entry
			table.insert(study_queue, deferred_entry)
			-- We no longer decrement question_num here so that it visibly advances
			-- even when skipping, up to a maximum of 'total'.
		end

		local function flash_hint_if_needed()
			if has_hint and config.hint_flash_duration and config.hint_flash_duration > 0 then
				local flash_context = mask_context(
					entry.context,
					target_word,
					config.exact_length_mask,
					has_hint,
					hint_n,
					hint_k,
					hint_m,
					nil,
					nil,
					config.case_sensitive_diff,
					config.ignore_punctuation,
					entry.source_index,
					false,
					config.blank_inverted_colors,
					config.blank_color
				)
				
				if config.single_card_mode then
					clear_screen()
				end
				print_header(config)
				
				local basename = entry.filename:match("([^/\\]+)$") or entry.filename
				if entry.is_repeat and not config.repeat_counts_in_stats then
					local header_prefix = entry.original_question_num and string.format("Practice Repeat %d/%d:", entry.original_question_num, total) or "Practice Repeat (Sync):"
					print(bold(cyan(header_prefix)) .. dim(string.format(" [File: %s | Box %d]", basename, entry.box)))
				else
					local cycle = math.ceil(question_num / total)
					local disp_num = ((question_num - 1) % total) + 1
					local cycle_str = cycle > 1 and string.format(" (Cycle %d)", cycle) or ""
					local repeat_str = entry.is_repeat and " (Repeat)" or ""
					print(bold(cyan(string.format("Question %d/%d%s%s:", disp_num, total, cycle_str, repeat_str))) .. dim(string.format(" [File: %s | Box %d]", basename, entry.box)))
				end
				
				print(wrap_text(flash_context))
				if current_hint and not config.exact_length_mask and config.show_hint then
					print(current_hint)
				end
				
				io.flush()
				local sleep_cmd = string.format('%s -c "import time; time.sleep(%f)"', config.python_cmd, config.hint_flash_duration)
				os.execute(sleep_cmd)
				
				-- Clear hint
				has_hint = false
				hint_n = 0
				hint_k = 0
				hint_m = 0
				current_hint = nil
				
				redraw_needed = true
			end
		end

		while true do
			console_width = get_console_width()
			local masked_context = mask_context(
				entry.context,
				target_word,
				config.exact_length_mask,
				has_hint,
				hint_n,
				hint_k,
				hint_m,
				nil,
				nil,
				config.case_sensitive_diff,
				config.ignore_punctuation,
				entry.source_index,
				false,
				config.blank_inverted_colors,
				config.blank_color
			)

			local cur_redraw = redraw_needed
			redraw_needed = true

			if cur_redraw then
				if config.single_card_mode then
					clear_screen()
				end

				print_header(config)

				local basename = entry.filename:match("([^/\\]+)$") or entry.filename
				if entry.is_repeat and not config.repeat_counts_in_stats then
					local header_prefix
					if entry.original_question_num then
						header_prefix = string.format("Practice Repeat %d/%d:", entry.original_question_num, total)
					else
						header_prefix = "Practice Repeat (Sync):"
					end
					print(bold(cyan(header_prefix)) .. dim(string.format(" [File: %s | Box %d]", basename, entry.box)))
				else
					local cycle = math.ceil(question_num / total)
					local disp_num = ((question_num - 1) % total) + 1
					local cycle_str = cycle > 1 and string.format(" (Cycle %d)", cycle) or ""
					local repeat_str = entry.is_repeat and " (Repeat)" or ""
					print(
						bold(cyan(string.format("Question %d/%d%s%s:", disp_num, total, cycle_str, repeat_str)))
							.. dim(string.format(" [File: %s | Box %d]", basename, entry.box))
					)
				end
				print(wrap_text(masked_context))
				if current_hint and not config.exact_length_mask and config.show_hint then
					print(current_hint)
				end
			end
			local user_input = ""
			local trimmed_input = ""
			local switch_mode = false

			if config.command_mode and is_command_mode then
				if config.command_mode_single_key then
					local allowed = {"a", "d", "y", "q", "?", "\r", "\n", "\x1b", "h", "/", " ", "/hint_left", "/hint_right", "/hint_up", "/hint_down"}
					local _cmd_color_fn = get_prompt_color_fn(config.command_mode_prompt_color)
					local key = press_any_key(bold(_cmd_color_fn and _cmd_color_fn("Command") or "Command") .. dim(" (press '?' for help)... "), allowed, config.command_mode_arrow_hints)
					if key == "" then
						local line = io.read()
						key = line and line:sub(1, 1) or ""
						if key == "" then key = "\r" end
					end
					local lkey = key:lower()
					if key:sub(1, 1) == "/" and key ~= "/" then
						trimmed_input = key
					elseif lkey == "\r" or lkey == "\n" or lkey == " " then
						switch_mode = true
						is_command_mode = false
						if config.single_card_mode and config.typing_preview then
							redraw_needed = false
						end
					elseif lkey == "\x1b" then
						if config.command_mode_esc_toggles then
							is_command_mode = false
							switch_mode = true
							if config.single_card_mode and config.typing_preview then
								redraw_needed = false
							end
						else
							trimmed_input = "/d"
						end
					elseif lkey == "d" then
						trimmed_input = "/d"
					elseif lkey == "a" then
						trimmed_input = "/a"
					elseif lkey == "y" then
						trimmed_input = "/y"
					elseif lkey == "q" then
						trimmed_input = "/q"
					elseif lkey == "?" then
						trimmed_input = "/?"
					elseif lkey == "h" then
						trimmed_input = "/h"
					elseif lkey == "/hint_left" or lkey == "/hint_right" or lkey == "/hint_up" or lkey == "/hint_down" then
						trimmed_input = lkey
					elseif lkey == "/" then
						io.write("/")
						local rest = read_line_with_esc(config, nil, false, false)
						if not rest then
							print(magenta("\nExiting quiz early."))
							return
						end
						trimmed_input = "/" .. rest:gsub("^%s+", ""):gsub("%s+$", "")
					else
						trimmed_input = ""
					end
				else
					local save_command = config.command_mode_save_command
					if cur_redraw then
						local _cmd_color_fn2 = get_prompt_color_fn(config.command_mode_prompt_color)
						io.write(bold(_cmd_color_fn2 and _cmd_color_fn2("Command") or "Command") .. dim(" (type '?' for help): "))
					end
					user_input = read_line_with_esc(config, saved_command_input, save_command, config.command_mode_arrow_hints)
					if not user_input then
						print(magenta("\nExiting quiz early."))
						return
					end
					
					local esc_triggered = false
					if user_input:sub(1, 1) == "\27" or user_input:sub(1, 1) == "\x1b" then
						esc_triggered = true
						if save_command then
							saved_command_input = user_input:sub(2)
							user_input = "/d"
						else
							saved_command_input = ""
							user_input = user_input:sub(2)
						end
					else
						saved_command_input = ""
					end

					trimmed_input = user_input:gsub("^%s+", ""):gsub("%s+$", "")
					
					if trimmed_input == "" then
						is_command_mode = false
						switch_mode = true
						if config.single_card_mode and config.typing_preview then
							redraw_needed = false
						end
					elseif trimmed_input == "/d" and esc_triggered then
						if config.command_mode_esc_toggles then
							is_command_mode = false
							switch_mode = true
							if config.single_card_mode and config.typing_preview then
								redraw_needed = false
							end
						else
							-- esc_toggles=false: Esc in Command mode skips the card (same as /d).
							-- Fall through so /d is dispatched by the command handler below.
						end
					else
						if trimmed_input:sub(1, 1) ~= "/" and trimmed_input ~= "" then
							trimmed_input = "/" .. trimmed_input
						end
					end
				end
			else
				local preview_data = nil
				if config.typing_preview and config.single_card_mode then
					local preview_template = mask_context(
						entry.context,
						target_word,
						config.exact_length_mask,
						has_hint,
						hint_n,
						hint_k,
						hint_m,
						nil,
						nil,
						config.case_sensitive_diff,
						config.ignore_punctuation,
						entry.source_index,
						true, -- preview_format
						config.blank_inverted_colors,
						config.blank_color
					)
					local hint_masks = {}
					if has_hint and config.hint_flash_duration ~= 0 then
						for part in target_word:gmatch("[^%s]+") do
							table.insert(hint_masks, get_hint_masked_word(part, hint_n, hint_k, hint_m))
						end
					end
					local payload = {
						header = get_card_header(config, question_num, total, entry),
						template = preview_template,
						hint = (config.show_hint and current_hint) or "",
						hint_masks = hint_masks,
						prompt = (function() local _f = get_prompt_color_fn(config.answer_mode_prompt_color); return bold(_f and _f("Answer") or "Answer") .. dim(" (type '/?' for help): ") end)(),
						exact_length_mask = config.exact_length_mask,
						battleship_feedback = config.battleship_feedback,
						case_sensitive_diff = config.case_sensitive_diff,
						ignore_punctuation = config.ignore_punctuation,
						diff_inverted_colors = config.diff_inverted_colors,
						blank_inverted_colors = config.blank_inverted_colors,
						blank_color = config.blank_color
					}
					preview_data = to_hex(json_encode(payload))
				end
				if cur_redraw then
					if not preview_data or package.config:sub(1, 1) ~= "\\" or config.single_card_mode then
						local _ans_color_fn2 = get_prompt_color_fn(config.answer_mode_prompt_color)
						io.write(bold(_ans_color_fn2 and _ans_color_fn2("Answer") or "Answer") .. dim(" (type '/?' for help): "))
					end
				end
				user_input = read_line_with_esc(config, saved_input, config.command_mode_save_input, config.answer_mode_arrow_hints, preview_data)
				if not user_input then
					print(magenta("\nExiting quiz early."))
					return
				end

				local esc_pressed = false
				if user_input:sub(1, 1) == "\27" or user_input:sub(1, 1) == "\x1b" then
					esc_pressed = true
					if config.command_mode_save_input then
						saved_input = user_input:sub(2)
						user_input = "/d"
					else
						saved_input = ""
						user_input = user_input:sub(2)
					end
				else
					saved_input = ""
				end

				trimmed_input = user_input:gsub("^%s+", ""):gsub("%s+$", "")
				
				if config.command_mode and esc_pressed and trimmed_input == "/d" then
					is_command_mode = true
					switch_mode = true
				end
			end

			if not switch_mode then
				if trimmed_input:sub(1, 1) == "/" then
					local cmd_body = trimmed_input:sub(2):gsub("^%s+", ""):gsub("%s+$", "")
					local lower_cmd = cmd_body:lower()

				if lower_cmd == "q" or lower_cmd == "quit" or lower_cmd == "exit" then
					print(magenta("\nExiting quiz early."))
					return
				elseif lower_cmd == "help" or lower_cmd == "?" then
					print_interactive_help(config)
					print()
					if config.single_card_mode then
						press_any_key("Press 'Enter' or 'Space' to return to quiz... ", { "\r", "\n", " " })
					end
				elseif lower_cmd == "resize" then
					-- Do nothing, just loop again to redraw with updated console width
				else
					local function generate_hint_string(target, n, k, m)
						local len = utf8_len(target)
						local parts = {}
						for part in target:gmatch("[^%s]+") do
							table.insert(parts, part)
						end
						local hint_parts = {}
						for _, part in ipairs(parts) do
							table.insert(hint_parts, format_hint_text(part, n, k, m))
						end
						local hint_str = table.concat(hint_parts, " ")
						return bold(cyan("💡 Hint: ")) .. hint_str .. dim(string.format(" (length: %d)", len))
					end

					local hint_cmd, arg1, arg2, arg3 = cmd_body:match("^(hint)%s*(%d*)%s*(%d*)%s*(%d*)$")
					if not hint_cmd then
						hint_cmd, arg1, arg2, arg3 = cmd_body:match("^(h)%s*(%d*)%s*(%d*)%s*(%d*)$")
					end

					if lower_cmd == "hint_left" then
						hint_n = hint_n + 1
						current_hint = generate_hint_string(target_word, hint_n, hint_k, hint_m)
						has_hint = true
						flash_hint_if_needed()
					elseif lower_cmd == "hint_right" then
						hint_m = hint_m + 1
						current_hint = generate_hint_string(target_word, hint_n, hint_k, hint_m)
						has_hint = true
						flash_hint_if_needed()
					elseif lower_cmd == "hint_down" then
						hint_k = hint_k + 1
						current_hint = generate_hint_string(target_word, hint_n, hint_k, hint_m)
						has_hint = true
						flash_hint_if_needed()
					elseif lower_cmd == "hint_up" then
						hint_n = 0
						hint_k = 0
						hint_m = 0
						current_hint = nil
						has_hint = false
					elseif hint_cmd then
						local n, k, m = 1, 0, 0
						if arg3 ~= "" then
							n = tonumber(arg1) or 1
							k = tonumber(arg2) or 0
							m = tonumber(arg3) or 0
						elseif arg2 ~= "" then
							n = tonumber(arg1) or 1
							k = 0
							m = tonumber(arg2) or 0
						elseif arg1 ~= "" then
							n = tonumber(arg1) or 1
							k = 0
							m = 0
						end

						hint_n = n
						hint_k = k
						hint_m = m
						current_hint = generate_hint_string(target_word, hint_n, hint_k, hint_m)
						has_hint = true
						if not config.single_card_mode then
							print("\n")
						end
						flash_hint_if_needed()
					elseif lower_cmd == "a" then
						local target_idx = entry.is_repeat and ((entry.repeat_target_idx or i) - 1) or (i - 1)
						if target_idx >= 1 then
							local repeat_entry = make_repeat_entry(study_queue[target_idx], target_idx, study_queue)

							table.insert(study_queue, i + 1, repeat_entry)
							-- Re-insert current card so we can return to it after the repeat
							table.insert(study_queue, i + 2, entry)

							if not entry.is_repeat then
								question_num = question_num - 1
							end

							break
						else
							if config.command_mode_single_key then
								print()
							end
							print(bold(red("There is no previous card to repeat.")))
							if config.single_card_mode then
								press_any_key("Press 'Enter' or 'Space' to retry... ", { "\r", "\n", " " })
							end
						end
					elseif lower_cmd == "d" then
						if not config.single_card_mode then
							print(bold(yellow("\nSkipping card...")))
						end
						defer_current_card()
						break
					elseif lower_cmd == "y" or lower_cmd == "sync_forward" then
						sync_forward_to_mpv(entry, config)
					elseif lower_cmd:match("^sync%s+") or lower_cmd == "sync" then
						if not config.mpv_integration then
							if config.command_mode_single_key then
								print()
							end
							print(bold(red("MPV Integration is disabled in config.ini.")))
						else
							local zid, timestamp_str = cmd_body:match("^sync%s+(%d+)%s+([%d%.]+)")
							if zid then
								local timestamp = tonumber(timestamp_str) or 0.0
								local best_entry = nil
								local min_diff = math.huge
								
								for _, e in ipairs(master_vocab) do
									local e_filename = e.filename:match("([^/\\]+)$") or e.filename
									if e_filename:find(zid, 1, true) then
										local e_time = tonumber(e.timestamp) or tonumber(e.source_index) or 0.0
										local diff = math.abs(e_time - timestamp)
										if diff < min_diff then
											min_diff = diff
											best_entry = e
										end
									end
								end
								
								if best_entry then
									local sync_entry = {}
									for k, v in pairs(best_entry) do
										sync_entry[k] = v
									end
									sync_entry.is_repeat = true
									sync_entry.original_card = best_entry
									table.insert(study_queue, i + 1, sync_entry)
									defer_current_card()
									break
								else
									if config.command_mode_single_key then
										print()
									end
									print(bold(red("Could not find matching card for ZID: ")) .. zid)
								end
							end
						end
					else
						if config.command_mode_single_key then
							print()
						end
						print(bold(red("Unknown command: ")) .. trimmed_input .. ". Type '/?' for help.\n")
						if config.single_card_mode then
							press_any_key("Press 'Enter' or 'Space' to retry... ", { "\r", "\n", " " })
						end
					end
				end
			else
				local clean_input = trimmed_input:gsub("%s+", "")
				local correct_word = target_word:gsub("%s+", "")
				if config.ignore_punctuation then
					clean_input = clean_input:gsub("%p+", "")
					correct_word = correct_word:gsub("%p+", "")
				end

				-- Clean up input (convert to lowercase for checking, since grading is case-insensitive)
				clean_input = clean_input:lower()
				correct_word = correct_word:lower()

				local is_correct = (clean_input == correct_word)
				local save_ok, save_err = true, nil

				if not config.anki_grading then
					if not entry.is_repeat then
						if is_correct then
							score = score + 1
						end
					end
					if not entry.is_repeat or config.repeat_counts_in_stats then
						save_ok, save_err = update_and_save_progress(entry, is_correct, config)
					end
				end

				-- BACK SIDE (Result presentation)
				local function draw_back_side()
					if config.single_card_mode then
						clear_screen()
						print_header(config)
						local basename = entry.filename:match("([^/\\]+)$") or entry.filename
						if entry.is_repeat and not config.repeat_counts_in_stats then
							local header_prefix
							if entry.original_question_num then
								header_prefix = string.format("Practice Repeat %d/%d:", entry.original_question_num, total)
							else
								header_prefix = "Practice Repeat (Sync):"
							end
							print(
								bold(cyan(header_prefix))
									.. dim(string.format(" [File: %s | Box %d]", basename, entry.box))
							)
						else
							local cycle = math.ceil(question_num / total)
							local disp_num = ((question_num - 1) % total) + 1
							local cycle_str = cycle > 1 and string.format(" (Cycle %d)", cycle) or ""
							local repeat_str = entry.is_repeat and " (Repeat)" or ""
							print(
								bold(cyan(string.format("Question %d/%d%s%s:", disp_num, total, cycle_str, repeat_str)))
									.. dim(string.format(" [File: %s | Box %d]", basename, entry.box))
							)
						end
					end

					local revealed_context = mask_context(
						entry.context,
						target_word,
						config.exact_length_mask,
						false,
						0,
						0,
						0,
						is_correct,
						trimmed_input,
						config.case_sensitive_diff,
						config.ignore_punctuation,
						entry.source_index,
						false,
						config.blank_inverted_colors,
						config.blank_color
					)
					print(wrap_text(revealed_context))

					local show_diff = true
					if config.battleship_feedback and not config.show_diff_with_battleship then
						show_diff = false
					end

					if show_diff then
						print()
						local u_line, t_line = get_two_line_diff(
							trimmed_input,
							target_word,
							config.case_sensitive_diff,
							config.ignore_punctuation,
							config.diff_inverted_colors
						)
						print_framed_diff(u_line, t_line)
						print()
					end

					if entry.is_repeat and not config.repeat_counts_in_stats then
						print(dim("This was a practice repeat (progress & score unaffected)."))
					end
				end

				draw_back_side()

				if not config.anki_grading then
					if not save_ok then
						print(bold(red("Warning: ")) .. "Failed to save progress: " .. tostring(save_err))
					end

					if config.single_card_mode then
						local break_outer = false
						while true do
							local key = press_any_key(
								dim("Press 'Enter' or 'Space' to continue, type '?' for help... "),
								{ "\r", "\n", " ", "s", "a", "d", "y", "\x1b", "q", "?" }
							)
							if key == "" then
								local line = io.read()
								key = line and line:sub(1, 1) or ""
							end
							local lkey = key and key:lower()
							if key:sub(1, 1) == "/" then
								local cmd_body = key:sub(2):gsub("^%s+", ""):gsub("%s+$", "")
								local lower_cmd = cmd_body:lower()
								if lower_cmd:match("^sync%s+") or lower_cmd == "sync" then
									if not config.mpv_integration then
										print(bold(red("MPV Integration is disabled in config.ini.")))
									else
										local zid, timestamp_str = cmd_body:match("^sync%s+(%d+)%s+([%d%.]+)")
										if zid then
											local timestamp = tonumber(timestamp_str) or 0.0
											local best_entry = nil
											local min_diff = math.huge
											for _, e in ipairs(master_vocab) do
												local e_filename = e.filename:match("([^/\\]+)$") or e.filename
												if e_filename:find(zid, 1, true) then
													local e_time = tonumber(e.timestamp) or tonumber(e.source_index) or 0.0
													local diff = math.abs(e_time - timestamp)
													if diff < min_diff then
														min_diff = diff
														best_entry = e
													end
												end
											end
											if best_entry then
												local sync_entry = {}
												for k, v in pairs(best_entry) do
													sync_entry[k] = v
												end
												sync_entry.is_repeat = true
												sync_entry.original_card = best_entry
												table.insert(study_queue, i + 1, sync_entry)
												defer_current_card()
												break_outer = true
												break
											else
												print(bold(red("Could not find matching card for ZID: ")) .. zid)
											end
										end
									end
								elseif lower_cmd == "q" or lower_cmd == "quit" or lower_cmd == "exit" then
									print(magenta("\nExiting quiz early."))
									return
								end
							elseif lkey == "?" then
								print(bold(cyan("\nBack Side Options:")))
								print("  " .. bold("Enter, Space") .. "            Continue to the next card.")
								print("  " .. bold("s") .. "                       Repeat the current card.")
								print("  " .. bold("a") .. "                       Repeat the previous card.")
								print(
									"  "
										.. bold("d")
										.. ", "
										.. bold("Esc")
										.. "                  Skip the current card."
								)
								if config.mpv_integration then
									print("  " .. bold("y") .. "                       Sync current card to MPV.")
								end
								print("  " .. bold("q") .. "                       Exit the quiz.")
								print()
							elseif lkey == "y" then
								sync_forward_to_mpv(entry, config)
								if config.single_card_mode then
									draw_back_side()
								end
							elseif lkey == "q" then
								print(magenta("\nExiting quiz early."))
								return
							elseif lkey == "a" then
								local target_idx = entry.is_repeat and ((entry.repeat_target_idx or i) - 1) or (i - 1)
								if target_idx >= 1 then
									local repeat_entry = make_repeat_entry(study_queue[target_idx], target_idx, study_queue)
									table.insert(study_queue, i + 1, repeat_entry)
									break
								else
									io.write("\27[1F\27[J")
									print(bold(red("There is no previous card to repeat.")))
								end
							elseif lkey == "s" then
								local target_idx = entry.repeat_target_idx or i
								local repeat_entry = make_repeat_entry(entry, target_idx, study_queue)
								table.insert(study_queue, i + 1, repeat_entry)
								break
							elseif lkey == "d" or lkey == "\x1b" then
								break
							else
								break
							end
						end
						if break_outer then
							break
						end
					end
				else
					-- Anki manual grading mode
					local break_outer = false
					while true do
						local prompt_str = bold("Grade ") .. dim("(press '?' for help, override with '1' as incorrect, '3' as correct)... ")

						local allowed = { "\r", "\n", " ", "1", "3", "q", "?" }
						if config.single_card_mode then
							table.insert(allowed, "s")
							table.insert(allowed, "a")
							table.insert(allowed, "d")
							table.insert(allowed, "y")
							table.insert(allowed, "\x1b")
						end

						local key = press_any_key(prompt_str, allowed)
						if key == "" then
							local line = io.read()
							key = line and line:sub(1, 1) or ""
						end
						local lkey = key and key:lower()

						if key:sub(1, 1) == "/" then
							local cmd_body = key:sub(2):gsub("^%s+", ""):gsub("%s+$", "")
							local lower_cmd = cmd_body:lower()
							if lower_cmd:match("^sync%s+") or lower_cmd == "sync" then
								if not config.mpv_integration then
									print(bold(red("MPV Integration is disabled in config.ini.")))
								else
									local zid, timestamp_str = cmd_body:match("^sync%s+(%d+)%s+([%d%.]+)")
									if zid then
										local timestamp = tonumber(timestamp_str) or 0.0
										local best_entry = nil
										local min_diff = math.huge
										for _, e in ipairs(master_vocab) do
											local e_filename = e.filename:match("([^/\\]+)$") or e.filename
											if e_filename:find(zid, 1, true) then
												local e_time = tonumber(e.timestamp) or tonumber(e.source_index) or 0.0
												local diff = math.abs(e_time - timestamp)
												if diff < min_diff then
													min_diff = diff
													best_entry = e
												end
											end
										end
										if best_entry then
											local sync_entry = {}
											for k, v in pairs(best_entry) do
												sync_entry[k] = v
											end
											sync_entry.is_repeat = true
											sync_entry.original_card = best_entry
											table.insert(study_queue, i + 1, sync_entry)
											defer_current_card()
											break_outer = true
											break
										else
											print(bold(red("Could not find matching card for ZID: ")) .. zid)
										end
									end
								end
							elseif lower_cmd == "q" or lower_cmd == "quit" or lower_cmd == "exit" then
								print(magenta("\nExiting quiz early."))
								return
							end
						elseif lkey == "?" then
							print(bold(cyan("\nBack Side Options:")))
							print("  " .. bold("1") .. "                       Override as incorrect.")
							print("  " .. bold("3") .. "                       Override as correct.")
							print(
								"  "
									.. bold("Enter, Space")
									.. "            Accept auto-grade as "
									.. (is_correct and "Correct" or "Incorrect")
									.. "."
							)
							if config.single_card_mode then
								print("  " .. bold("s") .. "                       Save and repeat the current card.")
								print("  " .. bold("a") .. "                       Repeat the previous card.")
								print(
									"  "
										.. bold("d")
										.. ", "
										.. bold("Esc")
										.. "                  Skip the current card."
								)
								if config.mpv_integration then
									print("  " .. bold("y") .. "                       Sync current card to MPV.")
								end
							end
							print("  " .. bold("q") .. "                       Exit the quiz.")
							print()
						elseif lkey == "y" then
							sync_forward_to_mpv(entry, config)
							if config.single_card_mode then
								draw_back_side()
							end
						elseif lkey == "q" then
							print(magenta("\nExiting quiz early."))
							return
						elseif lkey == "a" then
							local target_idx = entry.is_repeat and ((entry.repeat_target_idx or i) - 1) or (i - 1)
							if target_idx >= 1 then
								local repeat_entry = make_repeat_entry(study_queue[target_idx], target_idx, study_queue)
								table.insert(study_queue, i + 1, repeat_entry)
								break
							else
								print(bold(red("\nThere is no previous card to repeat.")))
								if config.single_card_mode then
									press_any_key("Press 'Enter' or 'Space' to retry... ", { "\r", "\n", " " })
								end
							end
						elseif lkey == "s" then
							local graded_correct = is_correct
							if not entry.is_repeat then
								if graded_correct then
									score = score + 1
								end
							end
							if not entry.is_repeat or config.repeat_counts_in_stats then
								save_ok, save_err = update_and_save_progress(entry, graded_correct, config)
								if not save_ok then
									print(bold(red("Warning: ")) .. "Failed to save progress: " .. tostring(save_err))
								end
							end

							local target_idx = entry.repeat_target_idx or i
							local repeat_entry = make_repeat_entry(entry, target_idx, study_queue)
							table.insert(study_queue, i + 1, repeat_entry)
							break
						elseif lkey == "d" or lkey == "\x1b" then
							defer_current_card()
							break
						else
							local graded_correct
							if lkey == "1" then
								graded_correct = false
							elseif lkey == "3" then
								graded_correct = true
							else
								graded_correct = is_correct
							end

							if not entry.is_repeat then
								if graded_correct then
									score = score + 1
								end
							end
							if not entry.is_repeat or config.repeat_counts_in_stats then
								save_ok, save_err = update_and_save_progress(entry, graded_correct, config)
								if not save_ok then
									print(bold(red("Warning: ")) .. "Failed to save progress: " .. tostring(save_err))
								end
							end
							break
						end
					end
					if break_outer then
						break
					end
				end

				break -- Go to the next question
			end
			end
		end
	end

	if config.single_card_mode then
		clear_screen()
	end
	print(bold(green(string.format("Quiz finished! You scored %d out of %d.", score, total))))
end

-- Helper to check if file exists
local function file_exists(name)
	local f = io.open(name, "r")
	if f then
		f:close()
		return true
	end
	return false
end

-- Print standard help menu
print_help = function()
	print(bold(cyan("Kardenwort TSV Quiz")))
	print(bold(cyan("-------------------")))
	print("An interactive CLI study tool for vocabulary TSV files.\n")
	print(bold("Usage:"))
	print("  lua tsv_quiz.lua [file.tsv]\n")
	print(bold("Interactive Controls (during quiz):"))
	print("  " .. bold("/h") .. ", " .. bold("/hint") .. "               Reveal the first letter of the target word.")
	print("  " .. bold("/h N") .. "                    Reveal N letters from the start of the word.")
	print("  " .. bold("/h N M") .. "                  Reveal N letters from the start and M from the end.")
	print("  " .. bold("/h N K M") .. "                Reveal N from the start, K from the middle, M from the end.")
	print("  " .. bold("/a") .. "                      Repeat the previous card.")
	print("  " .. bold("/d") .. ", " .. bold("Esc") .. "                 Skip the current card.")
	print("  " .. bold("Arrows") .. "                  Dynamic visual hints (if enabled).")
	print("  " .. bold("/q") .. ", " .. bold("/quit") .. ", " .. bold("/exit") .. "        Exit the quiz.\n")
	print(bold("Supported TSV Format:"))
	print("  Requires headers (e.g. Quotation or WordSource and SentenceSource or SentenceSourceContextLeft).")
end

print_interactive_help = function(config)
	local desc_col = 26
	print()
	print(bold(cyan("Interactive Controls:")))
	print("  " .. bold("/h") .. ", " .. bold("/hint") .. "               Reveal the first letter of the target word.")
	print("  " .. bold("/h N") .. "                    Reveal N letters from the start of the word.")
	print("  " .. bold("/h N M") .. "                  Reveal N letters from the start and M from the end.")
	print("  " .. bold("/h N K M") .. "                Reveal N from the start, K from the middle, M from the end.")
	print("  " .. bold("Arrows") .. "                  Dynamic visual hints (if enabled).")
	if config and config.typing_preview then
		local preview_desc = "Live preview of typed answer in the blank."
		if config.battleship_feedback then
			preview_desc = "Live preview in the blank with green/red (Battleship) correctness feedback."
		end
		print("  " .. bold("Live Preview") .. "            " .. preview_desc)
	end
	print("  " .. bold("/a") .. "                      Repeat the previous card.")
	local esc_skip = (config and config.command_mode and config.command_mode_esc_toggles) and "     " or ", " .. bold("Esc")
	print("  " .. bold("/d") .. esc_skip .. "                 Skip the current card.")
	if config and config.mpv_integration then
		print("  " .. bold("/y") .. ", " .. bold("/sync_forward") .. "       Sync active card timestamp to MPV.")
		print("  " .. bold("/sync <zid> <time>") .. "      Jump to the card matching ZID and closest timestamp.")
	end
	print("  " .. bold("/q") .. ", " .. bold("/quit") .. ", " .. bold("/exit") .. "        Exit the quiz.")
	if config and config.command_mode then
		print("\n" .. bold(cyan("Command Mode enabled:")))
		local esc_cmd_mode = config.command_mode_esc_toggles and "Switch to Answer (from command)." or "Skip the current card."
		if config.command_mode_single_key then
			local single_keys = config.mpv_integration and "a, d, y, q, ?, h" or "a, d, q, ?, h"
			print("  " .. bold("Esc") .. "                     In Answer: Switch to Command.")
			print("  " .. bold("Esc") .. "                     In Command: " .. esc_cmd_mode)
			print("  " .. bold("Enter, Space") .. "            In Command: Switch to Answer.")
			local spaces = string.rep(" ", desc_col - 2 - utf8_len(single_keys))
			print("  " .. bold(single_keys) .. spaces .. "Execute commands instantly with single keystrokes.")
		else
			local multi_keys = config.mpv_integration and "a, d, y, q, ?" or "a, d, q, ?"
			print("  " .. bold("Esc") .. "                     In Answer: Switch to Command.")
			print("  " .. bold("Esc") .. "                     In Command: " .. esc_cmd_mode)
			print("  " .. bold("Enter") .. "                   In Command: Switch to Answer.")
			local spaces = string.rep(" ", desc_col - 2 - utf8_len(multi_keys))
			print("  " .. bold(multi_keys) .. spaces .. "Execute commands without typing the slash prefix (requires Enter).")
		end
	end
end

-- Helper to resolve Windows .lnk shortcuts in pure Lua
local function resolve_lnk(path)
	if not path:lower():match("%.lnk$") then
		return path
	end

	local f = io.open(path, "rb")
	if not f then
		return path
	end
	local data = f:read("*a")
	f:close()

	if #data < 76 or data:sub(1, 4) ~= "L\0\0\0" then
		return path
	end

	local ok, flags = pcall(string.unpack, "<I4", data, 21)
	if not ok then
		return path
	end
	local has_link_target_id_list = (flags & 0x01) ~= 0
	local has_link_info = (flags & 0x02) ~= 0

	local offset = 77 -- 1-based index
	if has_link_target_id_list then
		if offset + 2 > #data then
			return path
		end
		local id_list_size = string.unpack("<I2", data, offset)
		offset = offset + 2 + id_list_size
	end

	if not has_link_info then
		return path
	end

	if offset + 20 > #data then
		return path
	end
	local link_info_flags = string.unpack("<I4", data, offset + 8)
	local local_base_path_offset = string.unpack("<I4", data, offset + 16)

	if (link_info_flags & 0x01) ~= 0 then
		local start_pos = offset + local_base_path_offset
		local end_pos = start_pos
		while end_pos <= #data and string.byte(data, end_pos) ~= 0 do
			end_pos = end_pos + 1
		end
		local target = data:sub(start_pos, end_pos - 1)
		-- Map legacy project folder name to the current directory name
		target = target:gsub("20260622113607%-german", "20260622113607-kardenwort-quiz")
		return target
	end

	return path
end

-- Main entry point
local function main()
	local arg1 = arg[1]
	if arg1 == "--help" or arg1 == "-h" then
		print_help()
		return
	end

	local script_path = arg[0] or ""
	local dir = script_path:match("(.*[/\\])") or ""

	-- 1. Collect all input files and optional sync parameters
	local input_files = {}
	local start_sync_zid = nil
	local start_sync_time = nil

	local arg_idx = 1
	while arg_idx <= #arg do
		if arg[arg_idx] == "--sync" and arg_idx + 2 <= #arg then
			start_sync_zid = arg[arg_idx + 1]
			start_sync_time = tonumber(arg[arg_idx + 2])
			arg_idx = arg_idx + 3
		else
			table.insert(input_files, arg[arg_idx])
			arg_idx = arg_idx + 1
		end
	end

	if #input_files == 0 then
		table.insert(input_files, "data.tsv")
	end

	-- 2. Resolve relative paths and .lnk shortcuts
	local resolved_files = {}
	for _, file in ipairs(input_files) do
		local resolved_file = file
		if not resolved_file:match("^%a:[/\\]") and not resolved_file:match("^[/\\]") then
			resolved_file = dir .. resolved_file
		end
		resolved_file = resolve_lnk(resolved_file)
		table.insert(resolved_files, resolved_file)
	end

	-- Pre-validate file extensions to avoid verbose error cascade
	local invalid_exts = {
		srt = "a subtitle",
		vtt = "a subtitle",
		mp4 = "a video",
		mkv = "a video",
		avi = "a video",
		webm = "a video",
		mov = "a video",
		mp3 = "an audio",
		wav = "an audio",
		m4a = "an audio",
		png = "an image",
		jpg = "an image",
		jpeg = "an image",
		gif = "an image",
	}
	for _, file_path in ipairs(resolved_files) do
		local ext = file_path:match("%.([^%.]+)$")
		if ext then
			local file_type = invalid_exts[ext:lower()]
			if file_type then
				print(bold(red("Error: ")) .. string.format("Selected file '%s' appears to be %s file (.%s). Please select a vocabulary TSV file instead.", file_path, file_type, ext:lower()))
				return
			end
		end
	end



	-- Load config.ini
	local config_path = dir .. "config.ini"
	local config = load_config(config_path)
	active_config = config

	-- Load all vocabulary from resolved files
	master_vocab = {}
	local files_loaded = 0
	local total_files = #resolved_files

	for idx, file_path in ipairs(resolved_files) do
		if file_exists(file_path) then
			print(string.format("Loading: %s (%d/%d)", file_path, idx, total_files))
			local file_vocab, raw_rows, box_idx, due_idx, err = load_tsv(file_path, config)
			if file_vocab then
				files_loaded = files_loaded + 1
				for _, entry in ipairs(file_vocab) do
					entry.filename = file_path
					entry.raw_rows = raw_rows
					entry.box_idx = box_idx
					entry.due_idx = due_idx
					table.insert(master_vocab, entry)
				end
			else
				print(
					bold(red("Error loading: "))
						.. file_path
						.. string.format(" (%d/%d): ", idx, total_files)
						.. (err or "unknown error")
				)
			end
		else
			if #arg == 0 then
				print_help()
				print(
					bold(red("\nError: "))
						.. "Default vocabulary file '"
						.. file_path
						.. "' not found. Please provide a TSV file path."
				)
				return
			else
				print(
					bold(red("Error: "))
						.. "File not found: "
						.. file_path
						.. string.format(" (%d/%d)", idx, total_files)
				)
			end
		end
	end

	if files_loaded == 0 then
		if #arg > 0 then
			print(bold(red("\nError: ")) .. "No vocabulary files could be loaded.")
		end
		return
	else
		print(string.format("Successfully loaded %d/%d files.", files_loaded, total_files))
	end

	-- Leitner Scheduling
	local now = os.time()
	local due_queue = {}
	local new_queue = {}
	local future_queue = {}

	for _, entry in ipairs(master_vocab) do
		if entry.due == 0 then
			table.insert(new_queue, entry)
		elseif now >= entry.due then
			table.insert(due_queue, entry)
		else
			table.insert(future_queue, entry)
		end
	end

	-- Apply new card limits
	local active_new = {}
	local limit = config.new_cards_per_day
	if limit == -1 then
		active_new = new_queue
	else
		for i = 1, math.min(limit, #new_queue) do
			table.insert(active_new, new_queue[i])
		end
	end

	-- 1. Sort due reviews based on review_sort_order
	if config.review_sort_order == "random" then
		shuffle_table(due_queue)
	elseif config.review_sort_order == "order_added" then
		-- Already in sequential order, do nothing
	else -- "due_date" (default)
		table.sort(due_queue, function(a, b)
			if a.box ~= b.box then
				return a.box < b.box
			else
				return a.due < b.due
			end
		end)
	end

	-- 2. Sort new cards based on new_sort_order
	if config.new_sort_order == "random" then
		shuffle_table(active_new)
	end

	-- 3. Assemble study queue based on new_review_order
	local study_queue = {}
	if config.new_review_order == "new_first" then
		for _, card in ipairs(active_new) do
			table.insert(study_queue, card)
		end
		for _, card in ipairs(due_queue) do
			table.insert(study_queue, card)
		end
	elseif config.new_review_order == "mix" then
		-- Mix them together
		for _, card in ipairs(due_queue) do
			table.insert(study_queue, card)
		end
		for _, card in ipairs(active_new) do
			table.insert(study_queue, card)
		end
		shuffle_table(study_queue)
	else -- "review_first" (default)
		for _, card in ipairs(due_queue) do
			table.insert(study_queue, card)
		end
		for _, card in ipairs(active_new) do
			table.insert(study_queue, card)
		end
	end

	-- Check if we have anything to study
	if #study_queue == 0 and not (start_sync_zid and start_sync_time) then
		print(bold(green("\nAll caught up! No reviews are currently due.")))
		if #new_queue > 0 and limit > 0 then
			print(
				dim(
					string.format(
						"(You have %d new cards waiting. Daily new card limit of %d is reached. Update config.ini to review more.)",
						#new_queue,
						limit
					)
				)
			)
		end

		if #future_queue > 0 then
			table.sort(future_queue, function(a, b)
				return a.due < b.due
			end)
			local next_due_diff = future_queue[1].due - now
			print(dim(string.format("Next review is due in: %s.", format_time_diff(next_due_diff))))

			if config.study_ahead then
				print(bold(cyan('\nEntering "Study Ahead" mode (closest reviews first)...')))
				study_queue = future_queue
				run_quiz(study_queue, config, start_sync_zid, start_sync_time)
			end
		end
	else
		-- Print schedule summary
		if #study_queue > 0 then
			print(
				bold(cyan(string.format("Queue Summary: %d due reviews, %d new cards selected.", #due_queue, #active_new)))
			)
		end
		run_quiz(study_queue, config, start_sync_zid, start_sync_time)
	end
end

local function run_lua_eval()
	local eval_code = os.getenv("TEST_LUA_EVAL")
	if eval_code then
		_G.load_config = load_config
		_G.mask_context = mask_context
		_G.get_inline_colored_diff = get_inline_colored_diff
		_G.get_two_line_diff = get_two_line_diff
		_G.json_encode = json_encode
		_G.bold = bold
		_G.green = green
		_G.red = red
		_G.yellow = yellow
		_G.c = c
		_G.invert = invert
		local chunk, err = load(eval_code)
		if chunk then
			local ok_eval, eval_err = pcall(chunk)
			if not ok_eval then
				io.stderr:write("Eval error: " .. tostring(eval_err) .. "\n")
				os.exit(1)
			end
		else
			io.stderr:write("Load error: " .. tostring(err) .. "\n")
			os.exit(1)
		end
		os.exit(0)
	end
end

run_lua_eval()

local ok, err = pcall(main)
if not ok then
	print("\nExecution error:")
	print(err)
end

press_any_key("\nPress 'Enter' or 'Space' to exit... ", { "\r", "\n", " " })

