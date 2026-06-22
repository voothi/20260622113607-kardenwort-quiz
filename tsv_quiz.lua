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

-- 2. Function to load data from the TSV file using header mapping
local function load_tsv(filename)
    local vocabulary = {}
    local file, err = io.open(filename, "r")
    if not file then
        print("Error opening file: " .. tostring(err))
        return nil
    end

    local headers = nil
    local word_source_idx = nil
    local word_inflected_idx = nil
    local quotation_idx = nil
    local context_indices = {}

    for line in file:lines() do
        -- Skip comments that are not deck columns
        if line:sub(1, 1) == "#" and not line:match("^#deck") then
            -- Skip regular comments
        elseif line:match("^#deck") then
            -- This marks an Anki/deck configuration line; we skip it but note it's metadata
        elseif not headers then
            -- The first non-comment line contains the headers
            headers = split_line(line, "\t")
            
            -- Map header names to their column indices
            local found_cols = {}
            for idx, h in ipairs(headers) do
                local clean_header = h:gsub("%s+$", ""):gsub("^%s+", "")
                found_cols[clean_header] = idx
            end

            -- Find word indices
            word_source_idx = found_cols["WordSource"]
            word_inflected_idx = found_cols["WordSourceInflectedForm"]
            quotation_idx = found_cols["Quotation"]
            
            -- Define context candidates in order of preference
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
        else
            -- Parse data row
            if line:match("%S") then
                local columns = split_line(line, "\t")
                
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
                    table.insert(vocabulary, {
                        word = target_word,
                        context = context_sentence
                    })
                end
            end
        end
    end
    file:close()
    return vocabulary
end

-- 3. Run the interactive CLI quiz
local function run_quiz(vocab_list)
    if not vocab_list or #vocab_list == 0 then
        print("No vocabulary entries loaded.")
        return
    end

    print(bold(cyan("=== Kardenwort TSV Quiz ===")))
    print(dim("Fill in the blank '") .. yellow("___") .. dim("' based on the context sentence."))
    print(dim("Type 'q' or 'exit' to quit.\n"))

    local score = 0
    local total = #vocab_list

    for i, entry in ipairs(vocab_list) do
        -- Replace the target word in the context sentence with a blank placeholder
        -- Case insensitive replacement check or literal match
        local target_word = entry.word
        local placeholder = bold(yellow("___"))
        local masked_context = entry.context:gsub(target_word, placeholder)
        -- If gsub didn't match (due to casing or punctuation), fall back to lowercase replacement
        if masked_context == entry.context then
            masked_context = entry.context:gsub(target_word:lower(), placeholder)
        end

        local current_hint = nil
        while true do
            print(bold(cyan(string.format("Question %d/%d:", i, total))))
            print(bold("Context: ") .. masked_context)
            if current_hint then
                print(current_hint)
            end
            io.write(bold("Your answer ") .. dim("(type 'h N M' for a hint, 'q' to quit): "))
            
            local user_input = io.read()
            if not user_input then
                print(magenta("\nExiting quiz early."))
                return
            end

            -- Normalise input: trim leading/trailing whitespace
            local trimmed_input = user_input:gsub("^%s+", ""):gsub("%s+$", "")
            local lower_input = trimmed_input:lower()

            -- Check for exit commands: q, quit, exit
            if lower_input == "q" or lower_input == "quit" or lower_input == "exit" then
                print(magenta("\nExiting quiz early."))
                return
            end

            -- Match hint patterns: "hint N K M", "h N K M", "hint N M", "h N M", "hint N", "h N", "hint", "h"
            local hint_cmd, arg1, arg2, arg3 = trimmed_input:match("^(hint)%s*(%d*)%s*(%d*)%s*(%d*)$")
            if not hint_cmd then
                hint_cmd, arg1, arg2, arg3 = trimmed_input:match("^(h)%s*(%d*)%s*(%d*)%s*(%d*)$")
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
                -- Clean up input (strip spaces and convert to lowercase for checking)
                local clean_input = lower_input:gsub("%s+", "")
                local correct_word = target_word:gsub("%s+", ""):lower()

                if clean_input == correct_word then
                    print(bold(green("✅ Richtig!\n")))
                    score = score + 1
                else
                    print(string.format(bold(red("❌ Falsch.")) .. " The correct word is: '" .. green("%s") .. "'\n", target_word))
                end
                break -- Go to the next question
            end
        end
    end

    print(bold(green(string.format("Quiz finished! You scored %d out of %d.", score, total))))
end

-- Main entry point
local function main()
    local filename = arg[1] or "data.tsv"
    
    -- Resolve relative filename based on the script's location
    if not filename:match("^%a:[/\\]") and not filename:match("^[/\\]") then
        local script_path = arg[0] or ""
        local dir = script_path:match("(.*[/\\])") or ""
        filename = dir .. filename
    end

    print("Loading: " .. filename)
    local vocab = load_tsv(filename)
    if vocab then
        run_quiz(vocab)
    else
        print("Failed to load vocabulary.")
    end
end

local ok, err = pcall(main)
if not ok then
    print("\nExecution error:")
    print(err)
end

io.write("\nPress Enter to exit...")
local _ = io.read()
