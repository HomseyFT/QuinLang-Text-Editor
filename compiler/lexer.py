import math
from typing import List
from .tokens import Token, TokenType, KEYWORDS

# The largest finite value a 32-bit float can hold. A literal above it would
# otherwise be stored as infinity.
FLOAT32_MAX = 3.4028234663852886e38

# Anything else after a backslash is an error, so a typo in an escape does not
# turn into two characters nobody asked for.
ESCAPES = {
    'n': '\n',
    't': '\t',
    'r': '\r',
    '0': '\0',
    '\\': '\\',
    '"': '"',
}


class LexError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(message)
        self.line = line
        self.col = col

class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.tokens: List[Token] = []
        self.start = 0
        self.current = 0
        self.line = 1
        self.col = 1

    def tokenize(self) -> List[Token]:
        while not self._is_at_end():
            self.start = self.current
            self._scan_token()
        self.tokens.append(Token(TokenType.EOF, "", self.line, self.col))
        return self.tokens

    def _is_at_end(self) -> bool:
        return self.current >= len(self.source)

    def _advance(self) -> str:
        ch = self.source[self.current]
        self.current += 1
        self.col += 1
        return ch

    def _peek(self) -> str:
        if self._is_at_end():
            return "\0"
        return self.source[self.current]

    def _peek_next(self) -> str:
        if self.current + 1 >= len(self.source):
            return "\0"
        return self.source[self.current + 1]

    def _match(self, expected: str) -> bool:
        if self._is_at_end():
            return False
        if self.source[self.current] != expected:
            return False
        self.current += 1
        self.col += 1
        return True

    def _add_token(self, type_: TokenType, literal=None):
        text = self.source[self.start:self.current]
        self.tokens.append(Token(type_, text, self.line, self.col - (self.current - self.start), literal))

    def _scan_token(self):
        c = self._advance()
        if c in ' \r\t':
            return
        if c == '\n':
            self.line += 1
            self.col = 1
            return

        if c == '(':
            self._add_token(TokenType.LEFT_PAREN); return
        if c == ')':
            self._add_token(TokenType.RIGHT_PAREN); return
        if c == '{':
            self._add_token(TokenType.LEFT_BRACE); return
        if c == '}':
            self._add_token(TokenType.RIGHT_BRACE); return
        if c == '[':
            self._add_token(TokenType.LEFT_BRACKET); return
        if c == ']':
            self._add_token(TokenType.RIGHT_BRACKET); return
        if c == ',':
            self._add_token(TokenType.COMMA); return
        if c == '.':
            self._add_token(TokenType.DOT); return
        if c == '-':
            self._add_token(TokenType.MINUS); return
        if c == '+':
            self._add_token(TokenType.PLUS); return
        if c == ';':
            self._add_token(TokenType.SEMICOLON); return
        if c == '*':
            self._add_token(TokenType.STAR); return
        if c == '%':
            self._add_token(TokenType.PERCENT); return
        if c == '^':
            self._add_token(TokenType.CARET); return
        if c == '~':
            self._add_token(TokenType.TILDE); return
        if c == '@':
            self._add_token(TokenType.AT); return
        if c == '|':
            if self._match('|'):
                self._add_token(TokenType.OR_OR); return
            self._add_token(TokenType.PIPE); return
        if c == ':':
            self._add_token(TokenType.COLON); return
        if c == '&':
            # '&&' logical and, '&' address-of
            if self._match('&'):
                self._add_token(TokenType.AND_AND); return
            self._add_token(TokenType.AMP); return
        if c == '/':
            if self._match('/'):
                while self._peek() != '\n' and not self._is_at_end():
                    self._advance()
                return
            self._add_token(TokenType.SLASH); return
        if c == '!':
            self._add_token(TokenType.BANG_EQUAL if self._match('=') else TokenType.BANG); return
        if c == '=':
            self._add_token(TokenType.EQUAL_EQUAL if self._match('=') else TokenType.EQUAL); return
        if c == '<':
            if self._match('<'):
                self._add_token(TokenType.SHL); return
            self._add_token(TokenType.LESS_EQUAL if self._match('=') else TokenType.LESS); return
        if c == '>':
            if self._match('>'):
                self._add_token(TokenType.SHR); return
            self._add_token(TokenType.GREATER_EQUAL if self._match('=') else TokenType.GREATER); return
        if c == '"':
            self._string(); return
        if c.isdigit():
            self._number(); return
        if c.isalpha() or c == '_':
            self._identifier(); return # type: ignore        
        raise LexError(
            f"Unexpected character '{c}'",
            self.line,
            self.col - 1,)

    def _string(self):
        open_line, open_col = self.line, self.col - 1
        value_chars = []
        while self._peek() != '"' and not self._is_at_end():
            ch = self._advance()
            if ch == '\n':
                self.line += 1
                self.col = 1
            if ch == '\\':
                if self._is_at_end():
                    break  # the unterminated check below reports this
                esc = self._advance()
                if esc == '\n':
                    self.line += 1
                    self.col = 1
                if esc not in ESCAPES:
                    raise LexError(
                        f"Unknown escape sequence '\\{esc}' in string literal",
                        self.line, self.col - 2,
                    )
                value_chars.append(ESCAPES[esc])
                continue
            value_chars.append(ch)
        if self._is_at_end():
            raise LexError("Unterminated string literal", open_line, open_col)
        self._advance()
        value = ''.join(value_chars)
        self._add_token(TokenType.STRING, value)

    def _check_trailing(self):
        """Reject a numeric literal that runs straight into a letter.

        Without this `1e5` lexes as `1` followed by the identifier `e5`, which
        parses as two things and means neither. There is no exponent notation,
        so saying so is better than silently splitting the token.
        """
        if self._peek().isalnum() or self._peek() == '_':
            text = self.source[self.start:self.current]
            raise LexError(
                f"Unexpected character '{self._peek()}' after numeric literal '{text}'",
                self.line,
                self.col,
            )

    def _check_range(self, value: int, text: str):
        # int is a 16-bit type. Negation is a separate unary operator, so a
        # literal itself is always non-negative and must fit in a word.
        if value > 0xFFFF:
            raise LexError(
                f"Integer literal '{text}' does not fit in 16 bits (max 65535 / 0xFFFF)",
                self.line,
                self.col - (self.current - self.start),
            )

    def _number(self):
        if self.source[self.start] == '0' and self._peek() in ('x', 'X'):
            self._advance()
            digit_start = self.current
            while True:
                ch = self._peek()
                if ch.isdigit() or ('a' <= ch.lower() <= 'f'):
                    self._advance()
                else:
                    break
            if self.current == digit_start:
                raise LexError(
                    "Hex literal has no digits after '0x'",
                    self.line,
                    self.col - (self.current - self.start),
                )
            self._check_trailing()
            text = self.source[self.start:self.current]
            value = int(text[2:], 16)
            self._check_range(value, text)
            self._add_token(TokenType.NUMBER, value)
            return

        while self._peek().isdigit():
            self._advance()

        if self._peek() == '.':
            # A float needs digits on both sides. `1.` is rejected rather than
            # left as `1` followed by DOT, which would only fail later and
            # somewhere less helpful. Nothing else can follow a number with a
            # dot, so there is no ambiguity with field access to preserve.
            if not self._peek_next().isdigit():
                raise LexError(
                    "Float literal needs at least one digit after '.'",
                    self.line,
                    self.col,
                )
            self._advance()
            while self._peek().isdigit():
                self._advance()
            self._check_trailing()
            text = self.source[self.start:self.current]
            value = float(text)
            self._check_float_range(value, text)
            self._add_token(TokenType.FLOAT_NUMBER, value)
            return

        self._check_trailing()
        text = self.source[self.start:self.current]
        value = int(text)
        self._check_range(value, text)
        self._add_token(TokenType.NUMBER, value)

    def _check_float_range(self, value: float, text: str):
        # float() happily returns inf for a literal past the double range, and
        # struct.pack('f') would then store inf without complaint. A literal
        # that cannot be represented is a mistake, not a request for infinity.
        if not math.isfinite(value) or abs(value) > FLOAT32_MAX:
            raise LexError(
                f"Float literal '{text}' does not fit in a 32-bit float "
                f"(max {FLOAT32_MAX:g})",
                self.line,
                self.col - (self.current - self.start),
            )

    def _identifier(self):
        while self._peek().isalnum() or self._peek() == '_':
            self._advance()
        text = self.source[self.start:self.current]
        type_ = KEYWORDS.get(text, TokenType.IDENTIFIER)
        self._add_token(type_)
