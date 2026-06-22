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

local function bold(text)    return c("1", text) end
local function dim(text)     return c("90", text) end
local function cyan(text)    return c("36", text) end
local function green(text)   return c("32", text) end
local function yellow(text)  return c("33", text) end
local function red(text)     return c("31", text) end
local function magenta(text) return c("35", text) end

-- UTF-8 Safe string helpers
local function utf8_len(str)
    return utf8.len(str) or #str
end

local function utf8_sub(str, start_char, end_char)
    local len = utf8_len(str)
    start_char = start_char or 1
    end_char = end_char or len
    
    if start_char < 0 then start_char = len + start_char + 1 end
    if end_char < 0 then end_char = len + end_char + 1 end
    if start_char < 1 then start_char = 1 end
    if end_char > len then end_char = len end
    if start_char > end_char then return "" end
    
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
    if not num then return 0 end
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
        math.random() math.random() math.random()
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
local function press_any_key(prompt)
    io.write(prompt)
    io.flush()
    if package.config:sub(1,1) == "\\" then
        os.execute("pause >nul")
    else
        os.execute("read -n 1 -s -r -p ''")
    end
    print()
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
        exact_length_mask = false
    }

    local f = io.open(filename, "r")
    if not f then return config end

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
                    "WordSource", "WordSourceInflectedForm", "WordSource2", "Quotation",
                    "WordDestination", "SentenceSource", "Note", "SourceURL",
                    "Source-en-GB", "Source-en-US", "SentenceSourceIndex", "Deck"
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
        "SentenceGerman"
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
                    raw_columns = columns
                })
            end
        end
    end

    if #vocabulary == 0 then
        return nil, nil, nil, nil, "No valid vocabulary entries could be loaded (target word and context sentence required)."
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
        if not utf8 then error("No utf8 lib") end
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
        if not utf8 then error("No utf8 lib") end
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

-- Helper to mask or reveal a target word (including separable prefix verbs) in the context sentence
local function mask_context(context, target_word, use_exact, has_hint, hint_n, hint_k, hint_m, is_correct)
    local p1, p2 = target_word:match("^(.-)%s*%.%.%.%s*(.-)$")
    
    local function escape_pattern(text)
        return text:gsub("([^%w])", "%%%1")
    end
    
    if p1 and p2 then
        -- Separable verb case: p1 ... p2
        local r1, r2
        if is_correct ~= nil then
            r1 = is_correct and bold(green(p1)) or bold(red(p1))
            r2 = is_correct and bold(green(p2)) or bold(red(p2))
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
                    final_r1 = is_correct and bold(green(m1)) or bold(red(m1))
                    final_r2 = is_correct and bold(green(m2)) or bold(red(m2))
                end
                return final_r1 .. mid .. final_r2
            end)
            return masked, count
        end
        
        -- Try exact casing
        local res, count = try_replace(p1, p2)
        if count > 0 then return res end
        
        -- Try lowercase parts
        res, count = try_replace(p1:lower(), p2:lower())
        if count > 0 then return res end
        
        -- Try capitalized part1 and lowercase part2 (common in German sentences)
        local first = utf8_sub(p1, 1, 1):upper()
        local rest = utf8_sub(p1, 2)
        res, count = try_replace(first .. rest, p2:lower())
        if count > 0 then return res end
        
        return context
    else
        -- Regular single word case
        local replacement
        if is_correct ~= nil then
            replacement = is_correct and bold(green(target_word)) or bold(red(target_word))
        elseif has_hint and use_exact then
            local hint_word = get_hint_masked_word(target_word, hint_n, hint_k, hint_m)
            replacement = bold(yellow(hint_word))
        else
            local mask = get_mask_placeholder(target_word, use_exact)
            replacement = bold(yellow(mask))
        end
        
        local masked, count = context:gsub(target_word, replacement)
        if count > 0 then return masked end
        
        masked, count = context:gsub(target_word:lower(), replacement)
        if count > 0 then return masked end
        
        -- Also try capitalized word
        local first = utf8_sub(target_word, 1, 1):upper()
        local rest = utf8_sub(target_word, 2)
        masked, count = context:gsub(first .. rest, replacement)
        if count > 0 then return masked end
        
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

    for i, entry in ipairs(study_queue) do
        local target_word = entry.word
        local current_hint = nil
        local hint_n, hint_k, hint_m = 0, 0, 0
        local has_hint = false

        while true do
            local masked_context = mask_context(entry.context, target_word, config.exact_length_mask, has_hint, hint_n, hint_k, hint_m, nil)

            if config.single_card_mode then
                clear_screen()
            end

            print_header(config)

            local basename = entry.filename:match("([^/\\]+)$") or entry.filename
            print(bold(cyan(string.format("Question %d/%d:", i, total))) .. dim(string.format(" [File: %s | Box %d]", basename, entry.box)))
            print(bold("Context: ") .. masked_context)
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
                        local p1, p2 = target_word:match("^(.-)%s*%.%.%.%s*(.-)$")
                        local hint_str
                        if p1 and p2 then
                            local h1 = format_hint_text(p1, n, k, m)
                            local h2 = format_hint_text(p2, n, k, m)
                            hint_str = h1 .. " ... " .. h2
                        else
                            hint_str = format_hint_text(target_word, n, k, m)
                        end
                        current_hint = bold(cyan("💡 Hint: ")) .. hint_str .. dim(string.format(" (length: %d)", len))
                        hint_n = n
                        hint_k = k
                        hint_m = m
                        has_hint = true
                        print("\n")
                    else
                        print(bold(red("Unknown command: ")) .. trimmed_input .. ". Type '/h' for hint, '/q' to quit.\n")
                        if config.single_card_mode then
                            press_any_key("Press Enter or Space to retry...")
                        end
                    end
                end
            else
                -- Clean up input (strip spaces, dots/ellipses, and convert to lowercase for checking)
                local clean_input = trimmed_input:lower():gsub("%s+", ""):gsub("%.+", "")
                local correct_word = target_word:lower():gsub("%s+", ""):gsub("%.+", "")

                local now = os.time()
                local new_box = entry.box
                local is_correct = (clean_input == correct_word)

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

                local save_ok, save_err = save_tsv(entry.filename, entry.raw_rows)

                -- BACK SIDE (Result presentation)
                if config.single_card_mode then
                    clear_screen()
                    print_header(config)
                    local basename = entry.filename:match("([^/\\]+)$") or entry.filename
                    print(bold(cyan(string.format("Question %d/%d:", i, total))) .. dim(string.format(" [File: %s | Box %d]", basename, entry.box)))
                end

                local revealed_context = mask_context(entry.context, target_word, config.exact_length_mask, false, 0, 0, 0, is_correct)
                print(bold("Context: ") .. revealed_context)

                if is_correct then
                    print(bold(green("✅ Correct!\n")))
                else
                    print(string.format(bold(red("❌ Incorrect.")) .. " The correct word is: '" .. green("%s") .. "'\n", target_word))
                end

                if not save_ok then
                    print(bold(red("Warning: ")) .. "Failed to save progress: " .. tostring(save_err))
                end

                if config.single_card_mode then
                    press_any_key(dim("Press Enter or Space to continue..."))
                end

                break -- Go to the next question
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
    if not f then return path end
    local data = f:read("*a")
    f:close()

    if #data < 76 or data:sub(1, 4) ~= "L\0\0\0" then
        return path
    end

    local ok, flags = pcall(string.unpack, "<I4", data, 21)
    if not ok then return path end
    local has_link_target_id_list = (flags & 0x01) ~= 0
    local has_link_info = (flags & 0x02) ~= 0

    local offset = 77 -- 1-based index
    if has_link_target_id_list then
        if offset + 2 > #data then return path end
        local id_list_size = string.unpack("<I2", data, offset)
        offset = offset + 2 + id_list_size
    end

    if not has_link_info then
        return path
    end

    if offset + 20 > #data then return path end
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
                print(bold(red("\nError: ")) .. "Default vocabulary file '" .. file_path .. "' not found. Please provide a TSV file path.")
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
            print(dim(string.format("(You have %d new cards waiting. Daily new card limit of %d is reached. Update config.ini to review more.)", #new_queue, limit)))
        end
        
        if #future_queue > 0 then
            table.sort(future_queue, function(a, b) return a.due < b.due end)
            local next_due_diff = future_queue[1].due - now
            print(dim(string.format("Next review is due in: %s.", format_time_diff(next_due_diff))))

            if config.study_ahead then
                print(bold(cyan("\nEntering \"Study Ahead\" mode (closest reviews first)...")))
                study_queue = future_queue
                run_quiz(study_queue, config)
            end
        end
    else
        -- Print schedule summary
        print(bold(cyan(string.format("Queue Summary: %d due reviews, %d new cards selected.", #due_queue, #active_new))))
        run_quiz(study_queue, config)
    end
end

local ok, err = pcall(main)
if not ok then
    print("\nExecution error:")
    print(err)
end

press_any_key("\nPress Enter or Space to exit...")
