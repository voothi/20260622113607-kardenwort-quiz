local utf8 = require("utf8")

local function c(code, text)
    return string.format("\27[%sm%s\27[0m", code, text)
end

local function dim(text)     return c("90", text) end
local function green(text)   return c("32", text) end
local function red(text)     return c("31", text) end

local function get_two_line_diff(user_str, target_str)
    local function clean_for_diff(str)
        local cleaned = str:gsub("%p+", "")
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
        if ok then return chars end
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
        for j = 1, m do
            if A[i]:lower() == B[j]:lower() then
                dp[i][j] = dp[i-1][j-1] + 1
            else
                dp[i][j] = math.max(dp[i-1][j], dp[i][j-1])
            end
        end
    end

    local i = n
    local j = m
    local ops = {}

    while i > 0 or j > 0 do
        if i > 0 and j > 0 and A[i]:lower() == B[j]:lower() then
            table.insert(ops, { type = "match", charA = A[i], charB = B[j] })
            i = i - 1
            j = j - 1
        elseif j > 0 and (i == 0 or dp[i][j-1] >= dp[i-1][j]) then
            table.insert(ops, { type = "missing", charA = "-", charB = B[j] })
            j = j - 1
        else
            table.insert(ops, { type = "extra", charA = A[i], charB = "-" })
            i = i - 1
        end
    end

    local user_parts = {}
    local target_parts = {}

    for k = #ops, 1, -1 do
        local op = ops[k]
        if op.type == "match" then
            table.insert(user_parts, dim(op.charA))
            table.insert(target_parts, dim(op.charB))
        elseif op.type == "missing" then
            table.insert(user_parts, red(op.charA))
            table.insert(target_parts, green(op.charB))
        elseif op.type == "extra" then
            table.insert(user_parts, red(op.charA))
            table.insert(target_parts, green(op.charB))
        end
    end

    return table.concat(user_parts, ""), table.concat(target_parts, "")
end

local user = "Abent vorbeu wie schon"
local target = "Abend vorbei. Wir schlagen"
local u, t = get_two_line_diff(user, target)
print(u)
print(t)
