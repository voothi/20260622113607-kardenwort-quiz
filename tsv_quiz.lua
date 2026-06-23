-- tsv_quiz.lua
-- A command-line utility to parse vocabulary from a TSV file and run a study quiz.
-- Demonstrates core Lua concepts: File I/O, tables, loops, string parsing, and interactive console input.

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
local function is_header_row(columns)
	for _, col in ipairs(columns) do
		local c = col:gsub("%s+$", ""):gsub("^%s+", ""):lower()
		if c == "wordsource" or c == "quotation" or c == "wordsourceinflectedform" or c == "sentencesource" then
			return true
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
local function press_any_key(prompt, allowed_keys)
	io.write(prompt)
	io.flush()
	while true do
		local key = ""
		if package.config:sub(1, 1) == "\\" then
			local f = io.popen(
				"python -c \"import msvcrt, sys; ch = msvcrt.getch() if sys.stdin.isatty() else b''; print(ch.decode('utf-8', 'ignore') if isinstance(ch, bytes) else ch, end='')\" 2>nul"
			)
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
			print()
			return key
		end

		if not allowed_keys then
			print()
			return key
		end

		local lkey = key:lower()
		for _, v in ipairs(allowed_keys) do
			if key == v or lkey == v then
				print()
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
		exact_length_mask = false,
		case_sensitive_diff = true,
		ignore_punctuation = true,
	}

	local f = io.open(filename, "r")
	if not f then
		return config
	end

	local current_section = nil
	for line in f:lines() do
		-- Remove comments and whitespace
		local clean = line:gsub("%s*#.*", ""):gsub("%s*;.*", ""):gsub("^%s+", ""):gsub("%s+$", "")
		if clean ~= "" then
			local section = clean:match("^%[(.+)%]$")
			if section then
				current_section = section:lower()
			elseif current_section == "leitner" then
				local key, val = clean:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
				if key and val then
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
					elseif key == "exact_length_mask" then
						config.exact_length_mask = (val == "true" or val == "1")
					elseif key == "case_sensitive_diff" then
						config.case_sensitive_diff = (val == "true" or val == "1")
					elseif key == "ignore_punctuation" then
						config.ignore_punctuation = (val == "true" or val == "1")
					end
				end
			end
		end
	end
	f:close()
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
local function load_tsv(filename)
	local vocabulary = {}
	local raw_rows = {}
	local file, err = io.open(filename, "r")
	if not file then
		return nil, nil, nil, nil, "Could not open file: " .. tostring(err)
	end

	local headers = nil
	local word_source_idx = nil
	local word_inflected_idx = nil
	local quotation_idx = nil
	local context_indices = {}

	local total_lines = 0
	local parsed_rows = 0

	for line in file:lines() do
		total_lines = total_lines + 1
		-- Store comment lines directly
		if line:sub(1, 1) == "#" then
			table.insert(raw_rows, { type = "comment", content = line })
		elseif not headers then
			-- This is the first non-comment line. Check if it is a header row
			local cols = split_line(line, "\t")
			if is_header_row(cols) then
				headers = cols
				table.insert(raw_rows, { type = "header", columns = cols })
			else
				-- Headerless! Generate default headers
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
				table.insert(raw_rows, { type = "header", columns = headers })

				-- Process this first line as a data row
				parsed_rows = parsed_rows + 1
				table.insert(raw_rows, { type = "data", columns = cols })
			end
		else
			-- Already have headers, parse as data row
			local cols = split_line(line, "\t")
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
	for idx, h in ipairs(headers) do
		local clean_header = h:gsub("%s+$", ""):gsub("^%s+", "")
		if clean_header == "LeitnerBox" then
			box_idx = idx
		elseif clean_header == "LeitnerDue" then
			due_idx = idx
		end
	end

	if not box_idx then
		table.insert(headers, "LeitnerBox")
		box_idx = #headers
	end
	if not due_idx then
		table.insert(headers, "LeitnerDue")
		due_idx = #headers
	end

	-- Map header names to their column indices for target word & context sentence extraction
	local found_cols = {}
	for idx, h in ipairs(headers) do
		local clean_header = h:gsub("%s+$", ""):gsub("^%s+", "")
		found_cols[clean_header] = idx
	end

	word_source_idx = found_cols["WordSource"]
	word_inflected_idx = found_cols["WordSourceInflectedForm"]
	quotation_idx = found_cols["Quotation"]

	local context_indices = {}
	local candidates = {
		"SentenceSource",
		"SentenceSourceContextLeft",
		"WordSourceContext",
		"SentenceSourceRewriteAISentenceSource",
		"SentenceGerman",
	}
	for _, name in ipairs(candidates) do
		if found_cols[name] then
			table.insert(context_indices, found_cols[name])
		end
	end
	if #context_indices == 0 then
		table.insert(context_indices, 6)
	end

	-- Now parse vocabulary data from raw_rows
	for _, row in ipairs(raw_rows) do
		if row.type == "data" then
			ensure_columns_len(row.columns, #headers)
			local columns = row.columns

			-- Determine target word based on dictionary (WordSource) vs phrase (WordSourceInflectedForm)
			local target_word = nil
			if word_source_idx and columns[word_source_idx] and columns[word_source_idx] ~= "" then
				target_word = columns[word_source_idx]
			elseif word_inflected_idx and columns[word_inflected_idx] and columns[word_inflected_idx] ~= "" then
				target_word = columns[word_inflected_idx]
			elseif quotation_idx and columns[quotation_idx] and columns[quotation_idx] ~= "" then
				target_word = columns[quotation_idx]
			end

			if not target_word or target_word == "" then
				target_word = columns[1]
			end

			-- Check candidates in priority order, picking the first non-empty value
			local context_sentence = nil
			for _, idx in ipairs(context_indices) do
				local val = columns[idx]
				if val and val ~= "" then
					context_sentence = val
					break
				end
			end

			if target_word and target_word ~= "" and context_sentence and context_sentence ~= "" then
				-- Parse Leitner values
				local box_val = tonumber(columns[box_idx]) or 1
				local due_val = tonumber(columns[due_idx]) or 0

				table.insert(vocabulary, {
					word = target_word,
					context = context_sentence,
					box = box_val,
					due = due_val,
					raw_columns = columns,
				})
			end
		end
	end

	if #vocabulary == 0 then
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
	print(bold(cyan("=== Kardenwort TSV Quiz ===")))
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
			if c:match("%s") or c:match("[%p%s]") then
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
			if c:match("%s") or c:match("[%p%s]") then
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
			if c:match("%s") or c:match("[%p%s]") then
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
			if c:match("%s") or c:match("[%p%s]") then
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

-- Helper to perform character-by-character diff (LCS-based) between user input and target word, returning two aligned lines
local function get_two_line_diff(user_str, target_str, case_sensitive, ignore_punctuation)
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

	local i = n
	local j = m
	local ops = {}

	while i > 0 or j > 0 do
		local match
		if case_sensitive then
			match = (i > 0 and j > 0 and A[i] == B[j])
		else
			match = (i > 0 and j > 0 and A[i]:lower() == B[j]:lower())
		end

		if match then
			table.insert(ops, { type = "match", charA = A[i], charB = B[j] })
			i = i - 1
			j = j - 1
		elseif j > 0 and dp[i][j] == dp[i][j - 1] + 1 then
			table.insert(ops, { type = "missing", charA = "-", charB = B[j] })
			j = j - 1
		elseif i > 0 and dp[i][j] == dp[i - 1][j] + 1 then
			table.insert(ops, { type = "extra", charA = A[i], charB = "-" })
			i = i - 1
		elseif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1 then
			table.insert(ops, { type = "replace", charA = A[i], charB = B[j] })
			i, j = i - 1, j - 1
		end
	end

	local user_parts = {}
	local target_parts = {}

	for k = #ops, 1, -1 do
		local op = ops[k]
		if op.type == "match" then
			table.insert(user_parts, green(op.charA))
			table.insert(target_parts, green(op.charB))
		elseif op.type == "replace" then
			table.insert(user_parts, red(op.charA))
			table.insert(target_parts, dim(op.charB))
		elseif op.type == "missing" then
			table.insert(user_parts, dim(op.charA))
			table.insert(target_parts, dim(op.charB))
		elseif op.type == "extra" then
			table.insert(user_parts, red(op.charA))
			table.insert(target_parts, dim(op.charB))
		end
	end

	return table.concat(user_parts, ""), table.concat(target_parts, "")
end

local function get_inline_colored_diff(user_str, original_target, case_sensitive, ignore_punctuation)
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

	local i, j = n, m
	local ops = {}
	while i > 0 or j > 0 do
		local match
		if case_sensitive then
			match = (i > 0 and j > 0 and A[i] == B[j])
		else
			match = (i > 0 and j > 0 and A[i]:lower() == B[j]:lower())
		end

		if match then
			table.insert(ops, { type = "match" })
			i, j = i - 1, j - 1
		elseif j > 0 and dp[i][j] == dp[i][j - 1] + 1 then
			table.insert(ops, { type = "missing" })
			j = j - 1
		elseif i > 0 and dp[i][j] == dp[i - 1][j] + 1 then
			-- deletion (extra in user, but inline diff only shows target characters)
			i = i - 1
		elseif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1 then
			table.insert(ops, { type = "replace" })
			i, j = i - 1, j - 1
		end
	end

	local tags = {}
	for k = #ops, 1, -1 do
		table.insert(tags, ops[k].type)
	end

	local res = {}
	local tag_idx = 1
	local orig_chars = to_chars(original_target)
	for _, ch in ipairs(orig_chars) do
		if ch:match("[%p%s]") then
			table.insert(res, bold(green(ch)))
		else
			local tag = tags[tag_idx] or "missing"
			tag_idx = tag_idx + 1
			if tag == "match" then
				table.insert(res, bold(green(ch)))
			else
				table.insert(res, bold(red(ch)))
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
	ignore_punctuation
)
	local p1, p2 = target_word:match("^(.-)%s*%.%.%.%s*(.-)$")

	local function escape_pattern(text)
		return text:gsub("([^%w])", "%%%1")
	end

	if p1 and p2 then
		-- Separable verb case: p1 ... p2
		local r1, r2
		if is_correct ~= nil then
			if is_correct then
				r1 = bold(green(p1))
				r2 = bold(green(p2))
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
				r1 = get_inline_colored_diff(user_p1, p1)
				r2 = get_inline_colored_diff(user_p2, p2)
			end
		elseif has_hint and use_exact then
			local hp1 = get_hint_masked_word(p1, hint_n, hint_k, hint_m)
			local hp2 = get_hint_masked_word(p2, hint_n, hint_k, hint_m)
			r1 = bold(yellow(hp1))
			r2 = bold(yellow(hp2))
		else
			local mask1 = get_mask_placeholder(p1, use_exact)
			local mask2 = get_mask_placeholder(p2, use_exact)
			r1 = bold(yellow(mask1))
			r2 = bold(yellow(mask2))
		end

		local function try_replace(p1_case, p2_case)
			local ep1 = escape_pattern(p1_case)
			local ep2 = escape_pattern(p2_case)
			local pattern = "(" .. ep1 .. ")(.-)(" .. ep2 .. ")"
			local masked, count = context:gsub(pattern, function(m1, mid, m2)
				local final_r1 = r1
				local final_r2 = r2
				if is_correct ~= nil then
					if is_correct then
						final_r1 = bold(green(m1))
						final_r2 = bold(green(m2))
					else
						final_r1 = r1
						final_r2 = r2
					end
				end
				return final_r1 .. mid .. final_r2
			end)
			return masked, count
		end

		-- Try exact casing
		local res, count = try_replace(p1, p2)
		if count > 0 then
			return res
		end

		-- Try lowercase parts
		res, count = try_replace(p1:lower(), p2:lower())
		if count > 0 then
			return res
		end

		-- Try capitalized part1 and lowercase part2 (common in German sentences)
		local first = utf8_sub(p1, 1, 1):upper()
		local rest = utf8_sub(p1, 2)
		res, count = try_replace(first .. rest, p2:lower())
		if count > 0 then
			return res
		end

		return context
	else
		-- Contiguous phrase or single word
		local parts = {}
		for part in target_word:gmatch("[^%s]+") do
			table.insert(parts, part)
		end

		local function get_part_replacement(part)
			if is_correct then
				return bold(green(part))
			elseif has_hint and use_exact then
				return bold(yellow(get_hint_masked_word(part, hint_n, hint_k, hint_m)))
			else
				return bold(yellow(get_mask_placeholder(part, use_exact)))
			end
		end

		local rep_parts = {}
		for _, part in ipairs(parts) do
			table.insert(rep_parts, get_part_replacement(part))
		end
		local replacement = table.concat(rep_parts, " ")

		local function try_single_replace(word_case)
			local e_word = escape_pattern(word_case)
			local masked, count = context:gsub(e_word, function(m)
				if is_correct ~= nil then
					if is_correct then
						local m_parts = {}
						for part in m:gmatch("[^%s]+") do
							table.insert(m_parts, part)
						end
						local m_rep_parts = {}
						for _, part in ipairs(m_parts) do
							table.insert(m_rep_parts, bold(green(part)))
						end
						return table.concat(m_rep_parts, " ")
					else
						return get_inline_colored_diff(user_input or "", m, case_sensitive_diff, ignore_punctuation)
					end
				else
					return replacement
				end
			end)
			return masked, count
		end

		local masked, count = try_single_replace(target_word)
		if count > 0 then
			return masked
		end

		masked, count = try_single_replace(target_word:lower())
		if count > 0 then
			return masked
		end

		local first = utf8_sub(target_word, 1, 1):upper()
		local rest = utf8_sub(target_word, 2)
		masked, count = try_single_replace(first .. rest)
		if count > 0 then
			return masked
		end

		return context
	end
end

-- 3. Run the interactive CLI quiz
local function run_quiz(study_queue, config)
	if not study_queue or #study_queue == 0 then
		print("No cards to review.")
		return
	end

	local score = 0
	local total = #study_queue
	local question_num = 0

	for i, entry in ipairs(study_queue) do
		if not entry.is_repeat then
			question_num = question_num + 1
		end
		local target_word = entry.word
		local current_hint = nil
		local hint_n, hint_k, hint_m = 0, 0, 0
		local has_hint = false

		while true do
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
				config.ignore_punctuation
			)

			if config.single_card_mode then
				clear_screen()
			end

			print_header(config)

			local basename = entry.filename:match("([^/\\]+)$") or entry.filename
			if entry.is_repeat then
				print(bold(cyan("Practice Repeat:")) .. dim(string.format(" [File: %s | Box %d]", basename, entry.box)))
			else
				print(
					bold(cyan(string.format("Question %d/%d:", question_num, total)))
						.. dim(string.format(" [File: %s | Box %d]", basename, entry.box))
				)
			end
			print(masked_context)
			if current_hint then
				print(current_hint)
			end
			io.write(bold("Your answer ") .. dim("(type '/h N M' for a hint, '/q' to quit): "))

			local user_input = io.read()
			if not user_input then
				print(magenta("\nExiting quiz early."))
				return
			end

			-- Normalise input: trim leading/trailing whitespace
			local trimmed_input = user_input:gsub("^%s+", ""):gsub("%s+$", "")

			if trimmed_input:sub(1, 1) == "/" then
				local cmd_body = trimmed_input:sub(2):gsub("^%s+", ""):gsub("%s+$", "")
				local lower_cmd = cmd_body:lower()

				if lower_cmd == "q" or lower_cmd == "quit" or lower_cmd == "exit" then
					print(magenta("\nExiting quiz early."))
					return
				else
					-- Match hint patterns: "hint N K M", "h N K M", "hint N M", "h N M", "hint N", "h N", "hint", "h"
					local hint_cmd, arg1, arg2, arg3 = cmd_body:match("^(hint)%s*(%d*)%s*(%d*)%s*(%d*)$")
					if not hint_cmd then
						hint_cmd, arg1, arg2, arg3 = cmd_body:match("^(h)%s*(%d*)%s*(%d*)%s*(%d*)$")
					end

					if hint_cmd then
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

						local len = utf8_len(target_word)
						local parts = {}
						for part in target_word:gmatch("[^%s]+") do
							table.insert(parts, part)
						end

						local hint_parts = {}
						for _, part in ipairs(parts) do
							table.insert(hint_parts, format_hint_text(part, n, k, m))
						end
						local hint_str = table.concat(hint_parts, " ")
						current_hint = bold(cyan("💡 Hint: ")) .. hint_str .. dim(string.format(" (length: %d)", len))
						hint_n = n
						hint_k = k
						hint_m = m
						has_hint = true
						print("\n")
					elseif lower_cmd == "a" then
						local target_idx = entry.is_repeat and ((entry.repeat_target_idx or i) - 1) or (i - 1)
						if target_idx >= 1 then
							local repeat_entry = {}
							for k, v in pairs(study_queue[target_idx]) do
								repeat_entry[k] = v
							end
							repeat_entry.is_repeat = true
							repeat_entry.repeat_target_idx = target_idx

							table.insert(study_queue, i + 1, repeat_entry)
							-- Re-insert current card so we can return to it after the repeat
							table.insert(study_queue, i + 2, entry)

							if not entry.is_repeat then
								question_num = question_num - 1
							end

							break
						else
							print(bold(red("There is no previous card to repeat.")))
							if config.single_card_mode then
								press_any_key("Press Enter or Space to retry...", { "\r", "\n", " " })
							end
						end
					elseif lower_cmd == "d" then
						print(bold(yellow("\nSkipping card...")))
						break
					else
						print(
							bold(red("Unknown command: "))
								.. trimmed_input
								.. ". Type '/h' for hint, '/q' to quit, '/a' to repeat previous, '/d' to skip.\n"
						)
						if config.single_card_mode then
							press_any_key("Press Enter or Space to retry...", { "\r", "\n", " " })
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

				if not entry.is_repeat then
					local now = os.time()
					local new_box = entry.box

					if is_correct then
						score = score + 1
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

					save_ok, save_err = save_tsv(entry.filename, entry.raw_rows)
				end

				-- BACK SIDE (Result presentation)
				if config.single_card_mode then
					clear_screen()
					print_header(config)
					local basename = entry.filename:match("([^/\\]+)$") or entry.filename
					if entry.is_repeat then
						print(
							bold(cyan("Practice Repeat:"))
								.. dim(string.format(" [File: %s | Box %d]", basename, entry.box))
						)
					else
						print(
							bold(cyan(string.format("Question %d/%d:", question_num, total)))
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
					config.ignore_punctuation
				)
				print(revealed_context)

				print()
				local u_line, t_line =
					get_two_line_diff(trimmed_input, target_word, config.case_sensitive_diff, config.ignore_punctuation)
				print_framed_diff(u_line, t_line)
				print()

				if entry.is_repeat then
					print(dim("This was a practice repeat. Your score and card progress were not affected."))
				end

				if not save_ok then
					print(bold(red("Warning: ")) .. "Failed to save progress: " .. tostring(save_err))
				end

				if config.single_card_mode then
					while true do
						local key = press_any_key(
							dim("Press Enter/Space to continue ('s' repeat, 'a' previous, 'd' skip, 'q' quit)..."),
							{ "\r", "\n", " ", "s", "a", "d", "q" }
						)
						local lkey = key and key:lower()
						if lkey == "q" then
							print(magenta("\nExiting quiz early."))
							return
						elseif lkey == "a" then
							local target_idx = entry.is_repeat and ((entry.repeat_target_idx or i) - 1) or (i - 1)
							if target_idx >= 1 then
								local repeat_entry = {}
								for k, v in pairs(study_queue[target_idx]) do
									repeat_entry[k] = v
								end
								repeat_entry.is_repeat = true
								repeat_entry.repeat_target_idx = target_idx
								table.insert(study_queue, i + 1, repeat_entry)
								break
							else
								io.write("\27[1F\27[J")
								print(bold(red("There is no previous card to repeat.")))
							end
						elseif lkey == "s" then
							local repeat_entry = {}
							for k, v in pairs(entry) do
								repeat_entry[k] = v
							end
							repeat_entry.is_repeat = true
							repeat_entry.repeat_target_idx = entry.repeat_target_idx or i
							table.insert(study_queue, i + 1, repeat_entry)
							break
						else
							-- For 'd', '\r', '\n', ' ' we just continue to the next card
							break
						end
					end
				end

				break -- Go to the next question
			end
		end
	end

	if config.single_card_mode then
		clear_screen()
	end
	print(bold(green(string.format("Quiz finished! You scored %d out of %d.", score, total))))
	press_any_key("\nPress Enter or Space to exit...", { "\r", "\n", " " })
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
local function print_help()
	print(bold(cyan("=== Kardenwort TSV Quiz ===")))
	print("An interactive CLI study tool for vocabulary TSV files.\n")
	print(bold("Usage:"))
	print("  lua tsv_quiz.lua [file.tsv]\n")
	print(bold("Interactive Controls (during quiz):"))
	print("  " .. bold("/h") .. " / " .. bold("/hint") .. "      Reveal first letter of the target word")
	print("  " .. bold("/h N") .. "        Reveal N letters from the start")
	print("  " .. bold("/h N M") .. "      Reveal N from the start and M from the end")
	print("  " .. bold("/h N K M") .. "    Reveal N from the start, K from the middle, M from the end")
	print("  " .. bold("/a") .. "                Practice repeat the previous card")
	print("  " .. bold("/d") .. "                Skip directly to the next card")
	print("  " .. bold("/q") .. " / " .. bold("/quit") .. " / " .. bold("/exit") .. " Exit the quiz immediately\n")
	print(bold("Supported TSV Format:"))
	print("  Requires headers (e.g. Quotation/WordSource and SentenceSource/SentenceSourceContextLeft).")
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
		return data:sub(start_pos, end_pos - 1)
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

	-- 1. Collect all input files
	local input_files = {}
	if #arg == 0 then
		table.insert(input_files, "data.tsv")
	else
		for i = 1, #arg do
			table.insert(input_files, arg[i])
		end
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

	-- Load config.ini
	local config_path = dir .. "config.ini"
	local config = load_config(config_path)

	-- Load all vocabulary from resolved files
	local master_vocab = {}
	local files_loaded = 0

	for _, file_path in ipairs(resolved_files) do
		if file_exists(file_path) then
			print("Loading: " .. file_path)
			local file_vocab, raw_rows, box_idx, due_idx, err = load_tsv(file_path)
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
				print(bold(red("Error loading ")) .. file_path .. ": " .. (err or "unknown error"))
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
				print(bold(red("Error: ")) .. "File not found: " .. file_path)
			end
		end
	end

	if files_loaded == 0 then
		if #arg > 0 then
			print(bold(red("\nError: ")) .. "No vocabulary files could be loaded.")
		end
		return
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
	if #study_queue == 0 then
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
				run_quiz(study_queue, config)
			end
		end
	else
		-- Print schedule summary
		print(
			bold(cyan(string.format("Queue Summary: %d due reviews, %d new cards selected.", #due_queue, #active_new)))
		)
		run_quiz(study_queue, config)
	end
end

local ok, err = pcall(main)
if not ok then
	print("\nExecution error:")
	print(err)
end

press_any_key("\nPress Enter or Space to exit...", { "\r", "\n", " " })
