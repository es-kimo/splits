package kr.splits.reservation.common

import org.springframework.http.HttpStatus

/**
 * 화면에 그대로 보여줄 수 있는 실패.
 * [code]는 프런트가 분기할 때 쓰고, [message]는 사용자에게 보이는 문장이다.
 */
open class ApiException(
    val status: HttpStatus,
    val code: String,
    override val message: String,
) : RuntimeException(message)

class BadRequestException(message: String, code: String = "BAD_REQUEST") :
    ApiException(HttpStatus.BAD_REQUEST, code, message)

class UnauthorizedException(message: String, code: String = "UNAUTHORIZED") :
    ApiException(HttpStatus.UNAUTHORIZED, code, message)

class NotFoundException(message: String, code: String = "NOT_FOUND") :
    ApiException(HttpStatus.NOT_FOUND, code, message)

class ConflictException(message: String, code: String = "CONFLICT") :
    ApiException(HttpStatus.CONFLICT, code, message)

class TooManyRequestsException(message: String, code: String = "TOO_MANY_REQUESTS") :
    ApiException(HttpStatus.TOO_MANY_REQUESTS, code, message)
