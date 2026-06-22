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

-- Simple INI parser for config.ini
local function load_config(filename)
    local config = {
        intervals = { 300, 3600, 86400, 259200, 604800 }, -- default seconds: 5m, 1h, 1d, 3d, 7d
        new_cards_per_day = 20,
        study_ahead = false,
        incorrect_penalty = "reset",
        new_review_order = "review_first",
        review_sort_order = "due_date",
        new_sort_order = "order_added"
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

-- 3. Run the interactive CLI quiz
local function run_quiz(study_queue, filename, raw_rows, box_idx, due_idx, config)
    if not study_queue or #study_queue == 0 then
        print("No cards to review.")
        return
    end

    print(bold(cyan("=== Kardenwort TSV Quiz ===")))
    print(dim("Fill in the blank '") .. yellow("___") .. dim("' based on the context sentence."))
    print(dim("Type '/q' or '/exit' to quit.\n"))

    local score = 0
    local total = #study_queue

    for i, entry in ipairs(study_queue) do
        local target_word = entry.word
        local placeholder = bold(yellow("___"))
        local masked_context = entry.context:gsub(target_word, placeholder)
        if masked_context == entry.context then
            masked_context = entry.context:gsub(target_word:lower(), placeholder)
        end

        local current_hint = nil
        while true do
            print(bold(cyan(string.format("Question %d/%d:", i, total))) .. dim(string.format(" [Box %d]", entry.box)))
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
                        local part_start = utf8_sub(target_word, 1, n)
                        local part_end = ""
                        if m > 0 then
                            part_end = utf8_sub(target_word, len - m + 1, len)
                        end

                        local hint_prefix = bold(cyan("💡 Hint: "))
                        if k == 0 then
                            if n + m >= len then
                                current_hint = string.format("%s%s (length: %d)", hint_prefix, green(target_word), len)
                            else
                                current_hint = string.format("%s%s...%s (length: %d)", hint_prefix, green(part_start), green(part_end), len)
                            end
                        else
                            local mid_start = math.floor((len - k) / 2) + 1
                            local mid_end = mid_start + k - 1
                            local part_mid = utf8_sub(target_word, mid_start, mid_end)

                            if n >= mid_start or mid_end >= len - m + 1 or n + k + m >= len then
                                current_hint = string.format("%s%s (length: %d)", hint_prefix, green(target_word), len)
                            else
                                current_hint = string.format("%s%s...%s...%s (length: %d)", hint_prefix, green(part_start), green(part_mid), green(part_end), len)
                            end
                        end
                        print("\n")
                    else
                        print(bold(red("Unknown command: ")) .. trimmed_input .. ". Type '/h' for hint, '/q' to quit.\n")
                    end
                end
            else
                -- Clean up input (strip spaces and convert to lowercase for checking)
                local clean_input = trimmed_input:lower():gsub("%s+", "")
                local correct_word = target_word:gsub("%s+", ""):lower()

                local now = os.time()
                local new_box = entry.box
                if clean_input == correct_word then
                    print(bold(green("✅ Correct!\n")))
                    score = score + 1
                    new_box = math.min(entry.box + 1, #config.intervals)
                else
                    print(string.format(bold(red("❌ Incorrect.")) .. " The correct word is: '" .. green("%s") .. "'\n", target_word))
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
                entry.raw_columns[box_idx] = tostring(new_box)
                entry.raw_columns[due_idx] = tostring(new_due)

                local save_ok, save_err = save_tsv(filename, raw_rows)
                if not save_ok then
                    print(bold(red("Warning: ")) .. "Failed to save progress: " .. tostring(save_err))
                end

                break -- Go to the next question
            end
        end
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

-- Main entry point
local function main()
    local arg1 = arg[1]
    if arg1 == "--help" or arg1 == "-h" then
        print_help()
        return
    end

    local filename = arg1 or "data.tsv"
    
    -- Resolve relative filename based on the script's location
    local script_path = arg[0] or ""
    local dir = script_path:match("(.*[/\\])") or ""

    if not filename:match("^%a:[/\\]") and not filename:match("^[/\\]") then
        filename = dir .. filename
    end

    if not file_exists(filename) then
        if not arg1 then
            print_help()
            print(bold(red("\nError: ")) .. "Default vocabulary file '" .. filename .. "' not found. Please provide a TSV file path.")
        else
            print(bold(red("Error: ")) .. "File not found: " .. filename)
        end
        return
    end

    -- Load config.ini
    local config_path = dir .. "config.ini"
    local config = load_config(config_path)

    print("Loading: " .. filename)
    local vocab, raw_rows, box_idx, due_idx, err = load_tsv(filename)
    if not vocab then
        print(bold(red("Error: ")) .. (err or "Failed to load vocabulary."))
        return
    end

    -- Leitner Scheduling
    local now = os.time()
    local due_queue = {}
    local new_queue = {}
    local future_queue = {}

    for _, entry in ipairs(vocab) do
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
                run_quiz(study_queue, filename, raw_rows, box_idx, due_idx, config)
            end
        end
    else
        -- Print schedule summary
        print(bold(cyan(string.format("Queue Summary: %d due reviews, %d new cards selected.", #due_queue, #active_new))))
        run_quiz(study_queue, filename, raw_rows, box_idx, due_idx, config)
    end
end

local ok, err = pcall(main)
if not ok then
    print("\nExecution error:")
    print(err)
end

io.write("\nPress Enter to exit...")
local _ = io.read()
