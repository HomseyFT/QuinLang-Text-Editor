from typing import List, Optional
from .tokens import Token, TokenType
from . import ast as A

class ParseError(Exception):
    def __init__(self, message: str, line: int, col: int):
        super().__init__(message)
        self.line = line
        self.col = col

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.current = 0

    def parse(self) -> A.Program:
        funcs: List[A.Function] = []
        while not self._is_at_end():
            funcs.append(self._function())
        return A.Program(funcs)

    # Helpers
    def _match(self, *types: TokenType) -> bool:
        for t in types:
            if self._check(t):
                self._advance()
                return True
        return False

    def _consume(self, type_: TokenType, msg: str) -> Token:
        if self._check(type_):
            return self._advance()
        tok = self._peek()
        raise ParseError(f"{msg} (found '{tok.lexeme}')", tok.line, tok.col)

    def _check(self, type_: TokenType) -> bool:
        if self._is_at_end():
            return False
        return self._peek().type == type_

    def _advance(self) -> Token:
        if not self._is_at_end():
            self.current += 1
        return self._previous()

    def _is_at_end(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _peek(self) -> Token:
        return self.tokens[self.current]

    def _previous(self) -> Token:
        return self.tokens[self.current - 1]

    # Grammar
    def _function(self) -> A.Function:
        self._consume(TokenType.FN, "Expected 'fn' at function start")
        name_tok = self._consume(TokenType.IDENTIFIER, "Expected function name")
        self._consume(TokenType.LEFT_PAREN, "Expected '(' after function name")
        params: List[A.Param] = []
        if not self._check(TokenType.RIGHT_PAREN):
            while True:
                p_name = self._consume(TokenType.IDENTIFIER, "Expected parameter name").lexeme
                self._consume(TokenType.COLON, "Expected ':' after parameter name")
                p_type = self._type_name()
                params.append(A.Param(p_name, p_type))
                if not self._match(TokenType.COMMA):
                    break
        self._consume(TokenType.RIGHT_PAREN, "Expected ')' after parameters")
        ret_type: Optional[str] = None
        if self._match(TokenType.COLON):
            ret_type = self._type_name()
        body = self._block()
        return A.Function(name_tok.lexeme, params, ret_type, body)

    def _type_name(self) -> str:
        # base scalar types
        if self._match(TokenType.INT):
            base = "int"
        elif self._match(TokenType.STR):
            base = "str"
        elif self._match(TokenType.VOID):
            base = "void"
        elif self._match(TokenType.PTR):
            base = "ptr"
        else:
            # allow identifiers for user-defined types in future
            tok = self._consume(TokenType.IDENTIFIER, "Expected type name")
            base = tok.lexeme

        # Optional fixed-size int array syntax: int[NUMBER]
        if base == "int" and self._match(TokenType.LEFT_BRACKET):
            # Expect a numeric literal for the length
            num_tok = self._consume(TokenType.NUMBER, "Expected array size after '['")
            self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after array size")
            return f"int[{int(num_tok.literal)}]"

        return base

    def _block(self) -> List[A.Stmt]:
        self._consume(TokenType.LEFT_BRACE, "Expected '{' to start block")
        stmts: List[A.Stmt] = []
        while not self._check(TokenType.RIGHT_BRACE):
            stmts.append(self._declaration())
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after block")
        return stmts

    def _declaration(self) -> A.Stmt:
        if self._match(TokenType.LET):
            return self._var_decl()
        return self._statement()

    def _var_decl(self) -> A.VarDecl:
        name = self._consume(TokenType.IDENTIFIER, "Expected variable name").lexeme
        type_name: Optional[str] = None
        init: Optional[A.Expr] = None
        if self._match(TokenType.COLON):
            type_name = self._type_name()
        if self._match(TokenType.EQUAL):
            init = self._expression()
        self._consume(TokenType.SEMICOLON, "Expected ';' after variable declaration")
        return A.VarDecl(name, type_name, init)

    def _statement(self) -> A.Stmt:
        if self._match(TokenType.PRINT):
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'print'")
            expr = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after print expression")
            self._consume(TokenType.SEMICOLON, "Expected ';' after print statement")
            return A.Print(expr)
        if self._match(TokenType.PRINTLN):
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'println'")
            expr = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after println expression")
            self._consume(TokenType.SEMICOLON, "Expected ';' after println statement")
            return A.PrintLn(expr)
        if self._match(TokenType.ASM):
            # Simple inline 8086 asm form: asm "...";
            tok = self._consume(TokenType.STRING, "Expected string literal after 'asm'")
            self._consume(TokenType.SEMICOLON, "Expected ';' after asm statement")
            return A.InlineAsm(tok.literal)
        if self._match(TokenType.VM_ASM):
            return self._vm_asm_block()
        if self._match(TokenType.RETURN):
            value: Optional[A.Expr] = None
            if not self._check(TokenType.SEMICOLON):
                value = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after return value")
            return A.Return(value)
        if self._match(TokenType.IF):
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'if'")
            cond = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after condition")
            then_block = self._block()
            else_block = None
            if self._match(TokenType.ELSE):
                else_block = self._block()
            return A.If(cond, then_block, else_block)
        if self._match(TokenType.WHILE):
            self._consume(TokenType.LEFT_PAREN, "Expected '(' after 'while'")
            cond = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after condition")
            body = self._block()
            return A.While(cond, body)
        # General expression / assignment form: `expr` or `expr = value`.
        expr = self._expression()
        if self._match(TokenType.EQUAL):
            value = self._expression()
            self._consume(TokenType.SEMICOLON, "Expected ';' after assignment")
            return A.Assign(expr, value)
        self._consume(TokenType.SEMICOLON, "Expected ';' after expression")
        return A.ExprStmt(expr)

    def _expression(self) -> A.Expr:
        return self._or()

    def _or(self) -> A.Expr:
        expr = self._and()
        while self._match(TokenType.OR_OR):
            op = self._previous().lexeme
            right = self._and()
            expr = A.Binary(expr, op, right)
        return expr

    def _and(self) -> A.Expr:
        expr = self._equality()
        while self._match(TokenType.AND_AND):
            op = self._previous().lexeme
            right = self._equality()
            expr = A.Binary(expr, op, right)
        return expr

    def _assignment(self) -> A.Expr:
        # assignment handled at statement level for simplicity
        return self._equality()

    def _equality(self) -> A.Expr:
        expr = self._comparison()
        while self._match(TokenType.EQUAL_EQUAL, TokenType.BANG_EQUAL):
            op = self._previous().lexeme
            right = self._comparison()
            expr = A.Binary(expr, op, right)
        return expr

    def _comparison(self) -> A.Expr:
        expr = self._term()
        while self._match(TokenType.GREATER, TokenType.GREATER_EQUAL, TokenType.LESS, TokenType.LESS_EQUAL):
            op = self._previous().lexeme
            right = self._term()
            expr = A.Binary(expr, op, right)
        return expr

    def _term(self) -> A.Expr:
        expr = self._factor()
        while self._match(TokenType.PLUS, TokenType.MINUS):
            op = self._previous().lexeme
            right = self._factor()
            expr = A.Binary(expr, op, right)
        return expr

    def _factor(self) -> A.Expr:
        expr = self._unary()
        while self._match(TokenType.STAR, TokenType.SLASH):
            op = self._previous().lexeme
            right = self._unary()
            expr = A.Binary(expr, op, right)
        return expr

    def _unary(self) -> A.Expr:
        # Address-of: &expr (limited to identifiers and indexing at sema/codegen)
        if self._match(TokenType.AMP):
            target = self._unary()
            return A.AddressOf(target)
        if self._match(TokenType.BANG, TokenType.MINUS):
            op = self._previous().lexeme
            right = self._unary()
            return A.Unary(op, right)
        return self._call()

    def _call(self) -> A.Expr:
        expr = self._primary()
        # Support chained postfix operators: calls and indexing.
        while True:
            # Function call: IDENT '(' args? ')'
            if isinstance(expr, A.Identifier) and self._match(TokenType.LEFT_PAREN):
                args: List[A.Expr] = []
                if not self._check(TokenType.RIGHT_PAREN):
                    while True:
                        args.append(self._expression())
                        if not self._match(TokenType.COMMA):
                            break
                self._consume(TokenType.RIGHT_PAREN, "Expected ')' after arguments")
                expr = A.Call(expr.name, args)
                continue
            # Indexing: expr '[' expression ']'
            if self._match(TokenType.LEFT_BRACKET):
                index_expr = self._expression()
                self._consume(TokenType.RIGHT_BRACKET, "Expected ']' after index expression")
                expr = A.Index(expr, index_expr)
                continue
            break
        return expr

    def _vm_asm_block(self) -> A.Stmt:
        # Parse: vm_asm { INSTR ...; INSTR2 ...; }
        self._consume(TokenType.LEFT_BRACE, "Expected '{' after 'vm_asm'")
        lines = []
        current_parts = []
        while not self._check(TokenType.RIGHT_BRACE):
            tok = self._advance()
            if tok.type == TokenType.SEMICOLON:
                # End of one vm_asm instruction line.
                current_parts.append(tok.lexeme)
                line = " ".join(current_parts).strip()
                if line:
                    lines.append(line)
                current_parts = []
            else:
                current_parts.append(tok.lexeme)
        self._consume(TokenType.RIGHT_BRACE, "Expected '}' after vm_asm block")
        code = "\n".join(lines)
        return A.VmAsm(code)

    def _primary(self) -> A.Expr:
        if self._match(TokenType.FALSE):
            return A.Literal(False)
        if self._match(TokenType.TRUE):
            return A.Literal(True)
        if self._match(TokenType.NUMBER):
            return A.Literal(self._previous().literal)
        if self._match(TokenType.STRING):
            return A.Literal(self._previous().literal)
        if self._match(TokenType.IDENTIFIER):
            return A.Identifier(self._previous().lexeme)
        if self._match(TokenType.LEFT_PAREN):
            expr = self._expression()
            self._consume(TokenType.RIGHT_PAREN, "Expected ')' after expression")
            return expr
        tok = self._peek()
        raise ParseError("Expected expression", tok.line, tok.col)
