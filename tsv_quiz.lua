-- tsv_quiz.lua
-- A command-line utility to parse vocabulary from a TSV file and run a study quiz.
-- Demonstrates core Lua concepts: File I/O, tables, loops, string parsing, and interactive console input.

-- 1. Helper function to split a string by a delimiter (tab in our case)
-- Concept: Functions, Loops, Table insertion, String pattern matching
local function split_line(line, delimiter)
    local result = {}
    -- "[^\t]+" matches anything that is not a tab character
    local pattern = string.format("([^%s]+)", delimiter)
    for part in string.gmatch(line, pattern) do
        table.insert(result, part)
    end
    return result
end

-- 2. Function to load data from the TSV file
-- Concept: File I/O (io.open), Conditionals, and multi-dimensional tables
local function load_tsv(filename)
    local vocabulary = {}
    local file, err = io.open(filename, "r")
    if not file then
        print("Error opening file: " .. tostring(err))
        return nil
    end

    for line in file:lines() do
        -- Skip empty lines
        if line:match("%S") then
            local columns = split_line(line, "\t")
            -- We want the word (Col 1) and the context sentence (Col 6)
            if #columns >= 6 then
                local entry = {
                    word = columns[1],
                    context = columns[6]
                }
                table.insert(vocabulary, entry)
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

    print("=== Deutsche Vokabeln B2 Quiz ===")
    print("Fill in the blank '___' based on the context sentence.")
    print("Type 'exit' to quit.\n")

    local score = 0
    local total = #vocab_list

    for i, entry in ipairs(vocab_list) do
        -- Replace the target word in the context sentence with a blank placeholder
        -- Case insensitive replacement check or literal match
        local target_word = entry.word
        local masked_context = entry.context:gsub(target_word, "___")
        -- If gsub didn't match (due to casing or punctuation), fall back to lowercase replacement
        if masked_context == entry.context then
            masked_context = entry.context:gsub(target_word:lower(), "___")
        end

        local current_hint = nil
        while true do
            print(string.format("Question %d/%d:", i, total))
            print("Context: " .. masked_context)
            if current_hint then
                print(current_hint)
            end
            io.write("Your answer (type 'h N M' for a hint, 'q' to quit): ")
            
            local user_input = io.read()
            if not user_input then
                print("\nExiting quiz early.")
                return
            end

            -- Normalise input: trim leading/trailing whitespace
            local trimmed_input = user_input:gsub("^%s+", ""):gsub("%s+$", "")
            local lower_input = trimmed_input:lower()

            -- Check for exit commands: q, quit, exit
            if lower_input == "q" or lower_input == "quit" or lower_input == "exit" then
                print("\nExiting quiz early.")
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
                
                local len = #target_word
                local part_start = target_word:sub(1, n)
                local part_end = ""
                if m > 0 then
                    part_end = target_word:sub(len - m + 1, len)
                end

                if k == 0 then
                    if n + m >= len then
                        current_hint = string.format("💡 Hint: %s (length: %d)", target_word, len)
                    else
                        current_hint = string.format("💡 Hint: %s...%s (length: %d)", part_start, part_end, len)
                    end
                else
                    local mid_start = math.floor((len - k) / 2) + 1
                    local mid_end = mid_start + k - 1
                    local part_mid = target_word:sub(mid_start, mid_end)

                    if n >= mid_start or mid_end >= len - m + 1 or n + k + m >= len then
                        current_hint = string.format("💡 Hint: %s (length: %d)", target_word, len)
                    else
                        current_hint = string.format("💡 Hint: %s...%s...%s (length: %d)", part_start, part_mid, part_end, len)
                    end
                end
                print("\n")
            else
                -- Clean up input (strip spaces and convert to lowercase for checking)
                local clean_input = lower_input:gsub("%s+", "")
                local correct_word = target_word:gsub("%s+", ""):lower()

                if clean_input == correct_word then
                    print("✅ Richtig!\n")
                    score = score + 1
                else
                    print(string.format("❌ Falsch. The correct word is: '%s'\n", target_word))
                end
                break -- Go to the next question
            end
        end
    end

    print(string.format("Quiz finished! You scored %d out of %d.", score, total))
end

-- Main entry point
local filename = "data.tsv"
local vocab = load_tsv(filename)
if vocab then
    run_quiz(vocab)
end
