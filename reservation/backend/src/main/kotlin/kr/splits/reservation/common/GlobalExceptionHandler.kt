package kr.splits.reservation.common

import org.slf4j.LoggerFactory
import org.springframework.dao.DataIntegrityViolationException
import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.http.converter.HttpMessageNotReadableException
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.bind.annotation.RestControllerAdvice
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException

data class ErrorResponse(
    val status: Int,
    val code: String,
    val message: String,
)

/**
 * 여기서 잡지 않은 예외(없는 경로, 지원하지 않는 메서드, 예상 못 한 오류)는
 * 스프링 기본 처리에 맡긴다. 전부 잡으면 404가 500으로 바뀐다.
 */
@RestControllerAdvice
class GlobalExceptionHandler {

    private val log = LoggerFactory.getLogger(javaClass)

    @ExceptionHandler(ApiException::class)
    fun handleApiException(e: ApiException): ResponseEntity<ErrorResponse> =
        ResponseEntity.status(e.status).body(ErrorResponse(e.status.value(), e.code, e.message))

    @ExceptionHandler(HttpMessageNotReadableException::class, MethodArgumentTypeMismatchException::class)
    fun handleUnreadable(e: Exception): ResponseEntity<ErrorResponse> =
        respond(HttpStatus.BAD_REQUEST, "BAD_REQUEST", "보낸 값을 읽을 수 없어요.")

    @ExceptionHandler(DataIntegrityViolationException::class)
    fun handleIntegrity(e: DataIntegrityViolationException): ResponseEntity<ErrorResponse> {
        log.warn("무결성 제약 위반: {}", e.mostSpecificCause.message)
        return respond(HttpStatus.CONFLICT, "CONFLICT", "이미 등록된 내용이에요. 화면을 새로 고쳐 주세요.")
    }

    private fun respond(status: HttpStatus, code: String, message: String) =
        ResponseEntity.status(status).body(ErrorResponse(status.value(), code, message))
}
