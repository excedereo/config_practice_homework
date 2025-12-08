import re
import sys
import copy
import click

NUMBER_RE = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")

# Глобальное состояние "парсера"
tokens = []   # список токенов: (type, value, line, col)
pos = 0       # текущая позиция в tokens
consts = {}   # константы: имя -> значение
config = {}   # верхнеуровневые параметры: имя -> значение

# ЛЕКСЕР

def lex(text: str):
    # Разбивает текст на токены и кладёт их в глобальный список tokens
    global tokens
    tokens = []

    line = 1
    col = 1
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # пробелы
        if ch in " \t\r":
            i += 1
            col += 1
            continue

        # перенос строки
        if ch == "\n":
            i += 1
            line += 1
            col = 1
            continue

        # комментарий до конца строки
        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
                col += 1
            continue

        # двухсимвольные токены
        if ch == ":" and i + 1 < n and text[i + 1] == "=":
            tokens.append(("ASSIGN", ":=", line, col))
            i += 2
            col += 2
            continue

        if ch == "-" and i + 1 < n and text[i + 1] == ">":
            tokens.append(("ARROW", "->", line, col))
            i += 2
            col += 2
            continue

        # односимвольные токены
        if ch in "[]{}@;":
            t = {
                "[": "LBRACKET",
                "]": "RBRACKET",
                "{": "LBRACE",
                "}": "RBRACE",
                "@": "AT",
                ";": "SEMICOLON",
            }[ch]
            tokens.append((t, ch, line, col))
            i += 1
            col += 1
            continue

        if ch == "+":
            tokens.append(("PLUS", "+", line, col))
            i += 1
            col += 1
            continue

        # '-' — либо начало числа, либо оператор
        if ch == "-":
            m = NUMBER_RE.match(text, i)
            if m:
                s = m.group(0)
                tokens.append(("NUMBER", s, line, col))
                i += len(s)
                col += len(s)
            else:
                tokens.append(("MINUS", "-", line, col))
                i += 1
                col += 1
            continue

        # числа, начиная с цифры или точки
        if ch.isdigit() or ch == ".":
            m = NUMBER_RE.match(text, i)
            if not m:
                raise Exception(f"Некорректное число в строке {line}, столбец {col}")
            s = m.group(0)
            tokens.append(("NUMBER", s, line, col))
            i += len(s)
            col += len(s)
            continue

        # идентификаторы / ключевые слова (begin/end)
        if ch.isalpha() or ch == "_":
            start = i
            start_col = col
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
                col += 1
            ident = text[start:i]
            t = "BEGIN" if ident == "begin" else "END" if ident == "end" else "IDENT"
            tokens.append((t, ident, line, start_col))
            continue

        raise Exception(f"Неожиданный символ '{ch}' в строке {line}, столбец {col}")

    # конец файла
    tokens.append(("EOF", "", line, col))

# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ПАРСЕРА

def peek():
    return tokens[pos]

def match(ttype):
    global pos
    if tokens[pos][0] == ttype:
        pos += 1
        return True
    return False

def consume(ttype, msg):
    global pos
    t = tokens[pos]
    if t[0] != ttype:
        raise Exception(
            f"{msg} в строке {t[2]}, столбец {t[3]} (встретилось {t[0]} '{t[1]}')"
        )
    pos += 1
    return t

def isnum(v):
    return isinstance(v, (int, float))

# ПАРСЕР ФАЙЛА

def parse_file():
    global pos, config
    pos = 0
    config = {}

    while tokens[pos][0] != "EOF":
        # пропускаем лишние ; между конструкциями
        while match("SEMICOLON"):
            pass

        if tokens[pos][0] == "EOF":
            break

        # присваивание: IDENT := value;
        if tokens[pos][0] == "IDENT" and tokens[pos + 1][0] == "ASSIGN":
            parse_assignment()
        else:
            # константа: value -> IDENT;
            parse_const()

    return config


def parse_assignment():
    name = consume("IDENT", "Ожидался идентификатор")[1]
    consume("ASSIGN", "Ожидался оператор ':='")
    v = parse_value()
    match("SEMICOLON")  # ; в конце делаем необязательным
    config[name] = v


def parse_const():
    v = parse_value()
    consume("ARROW", "Ожидался оператор '->'")
    name_tok = consume("IDENT", "Ожидалось имя константы")
    name = name_tok[1]
    if name in consts:
        raise Exception(
            f"Константа '{name}' повторно объявлена в строке {name_tok[2]}, столбец {name_tok[3]}"
        )
    consts[name] = v
    match("SEMICOLON")

# ПАРСИНГ ЗНАЧЕНИЙ

def parse_value():
    """Парсит значение: число, массив, словарь, @{...} или константу."""
    ttype, val, line, col = peek()

    # число
    if ttype == "NUMBER":
        consume("NUMBER", "Ожидалось число")
        return float(val) if any(c in val for c in ".eE") else int(val)

    # массив
    if ttype == "LBRACKET":
        return parse_array()

    # словарь
    if ttype == "BEGIN":
        return parse_dict()

    # константное выражение
    if ttype == "AT":
        return parse_constexpr()

    # использование константы как значения
    if ttype == "IDENT":
        consume("IDENT", "Ожидался идентификатор")
        if val not in consts:
            raise Exception(f"Неизвестная константа '{val}' в строке {line}, столбец {col}")
        return copy.deepcopy(consts[val])

    raise Exception(f"Ожидалось значение в строке {line}, столбец {col}")

def parse_array():
    consume("LBRACKET", "Ожидался символ '['")
    items = []
    if peek()[0] != "RBRACKET":
        items.append(parse_value())
        while match("SEMICOLON"):
            if peek()[0] == "RBRACKET":
                break
            items.append(parse_value())
    consume("RBRACKET", "Ожидался символ ']'")
    return items


def parse_dict():
    consume("BEGIN", "Ожидалось ключевое слово 'begin'")
    d = {}
    while peek()[0] != "END":
        key = consume("IDENT", "Ожидался ключ словаря")[1]
        consume("ASSIGN", "Ожидался оператор ':='")
        v = parse_value()
        consume("SEMICOLON", "Ожидался символ ';'")
        if key in d:
            raise Exception(f"Повторяющийся ключ '{key}' в словаре")
        d[key] = v
    consume("END", "Ожидалось ключевое слово 'end'")
    return d

# @{ ... }

def parse_constexpr():
    consume("AT", "Ожидался символ '@'")
    consume("LBRACE", "Ожидался символ '{'")
    v = parse_expr()
    consume("RBRACE", "Ожидался символ '}'")
    return v


def parse_expr():
    ttype, val, line, col = peek()

    if match("PLUS"):
        a = parse_expr()
        b = parse_expr()
        if not (isnum(a) and isnum(b)):
            raise Exception(f"Оператор '+' ожидает числовые аргументы (строка {line}, столбец {col})")
        return a + b

    if match("MINUS"):
        a = parse_expr()
        b = parse_expr()
        if not (isnum(a) and isnum(b)):
            raise Exception(f"Оператор '-' ожидает числовые аргументы (строка {line}, столбец {col})")
        return a - b

    if ttype == "IDENT" and val == "min":
        consume("IDENT", "Ожидалось слово 'min'")
        args = [parse_expr(), parse_expr()]
        while peek()[0] != "RBRACE":
            args.append(parse_expr())
        if not all(isnum(x) for x in args):
            raise Exception(f"Функция min() ожидает числовые аргументы (строка {line}, столбец {col})")
        return min(args)

    if ttype == "IDENT" and val == "sort":
        consume("IDENT", "Ожидалось слово 'sort'")
        arr = parse_expr()
        if not isinstance(arr, list):
            raise Exception(f"Функция sort() ожидает массив (строка {line}, столбец {col})")
        try:
            return sorted(arr)
        except TypeError:
            raise Exception(
                f"Элементы массива для sort() нельзя сравнить (строка {line}, столбец {col})"
            )

    return parse_value()

# ГЕНЕРАЦИЯ TOML

def render_scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return format(v, "g")
    if isinstance(v, str):
        return '"' + v.replace('"', '\\"') + '"'
    raise TypeError(f"Некорректный скалярный тип: {type(v)}")


def render_array(v):
    parts = []
    for x in v:
        if isinstance(x, dict):
            parts.append(render_inline(x))
        else:
            parts.append(render_scalar_or_array(x))
    return "[" + ", ".join(parts) + "]"


def render_inline(d):
    return "{ " + ", ".join(f"{k} = {render_scalar_or_array(v)}" for k, v in d.items()) + " }"


def render_scalar_or_array(v):
    if isinstance(v, (int, float, bool, str)):
        return render_scalar(v)
    if isinstance(v, list):
        return render_array(v)
    if isinstance(v, dict):
        return render_inline(v)
    raise TypeError(f"Некорректный тип значения: {type(v)}")


def emit_table(lines, fullname, d):
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(f"[{fullname}]")

    scalars = []
    arrays_of_tables = []
    nested = []

    for k, v in d.items():
        if isinstance(v, dict):
            nested.append((k, v))
        elif isinstance(v, list) and v and all(isinstance(el, dict) for el in v):
            arrays_of_tables.append((k, v))
        else:
            scalars.append((k, v))

    # обычные поля
    for k, v in scalars:
        lines.append(f"{k} = {render_scalar_or_array(v)}")

    # массивы таблиц
    for k, arr in arrays_of_tables:
        for el in arr:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[[{fullname}.{k}]]")
            for kk, vv in el.items():
                lines.append(f"{kk} = {render_scalar_or_array(vv)}")

    # вложенные словари как подтаблицы
    for k, v in nested:
        emit_table(lines, fullname + "." + k, v)

def generate_toml(cfg: dict) -> str:
    lines = []

    # корневые скаляры/массивы
    for k, v in cfg.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {render_scalar_or_array(v)}")

    # корневые словари как таблицы
    for k, v in cfg.items():
        if isinstance(v, dict):
            emit_table(lines, k, v)

    return "\n".join(lines) + "\n"

def convert(text: str) -> str:
    """Основная функция преобразования: текст учебного языка -> TOML."""
    consts.clear()
    lex(text)
    cfg = parse_file()
    return generate_toml(cfg)

# CLI через click

@click.command()
@click.option(
    "-i", "--input", "input_path", required=True, type=click.Path(exists=True, dir_okay=False),
    help="Входной файл с учебным конфигурационным языком",)
@click.option(
    "-o", "--output", "output_path", required=True, type=click.Path(dir_okay=False),
    help="Файл для вывода TOML",)
def cli(input_path, output_path):
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            text = f.read()
        toml = convert(text)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(toml)
    except Exception as e:
        raise click.ClickException(str(e))


if __name__ == "__main__":
    cli()