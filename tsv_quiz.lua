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

        print(string.format("Question %d/%d:", i, total))
        print("Context: " .. masked_context)
        io.write("Your answer: ")
        
        local user_input = io.read()
        if not user_input or user_input == "exit" then
            print("\nExiting quiz early.")
            break
        end

        -- Clean up input (strip spaces and convert to lowercase for checking)
        local clean_input = user_input:gsub("%s+", ""):lower()
        local correct_word = target_word:gsub("%s+", ""):lower()

        if clean_input == correct_word then
            print("✅ Richtig!\n")
            score = score + 1
        else
            print(string.format("❌ Falsch. The correct word is: '%s'\n", target_word))
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
