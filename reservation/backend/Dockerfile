# Stage 1: Build
FROM eclipse-temurin:17-jdk-jammy AS builder
WORKDIR /app

COPY gradlew settings.gradle.kts build.gradle.kts ./
COPY gradle ./gradle
RUN chmod +x gradlew

# 의존성 캐싱
RUN ./gradlew dependencies --no-daemon || true

COPY src ./src
RUN ./gradlew bootJar --no-daemon -x test

# Stage 2: Runtime
FROM eclipse-temurin:17-jre-jammy
WORKDIR /app

RUN addgroup --system --gid 1001 court && adduser --system --uid 1001 --ingroup court court
COPY --from=builder /app/build/libs/*.jar app.jar
USER court

# 운영(prod)은 HTTPS 8443, 그 밖의 프로필은 HTTP 8080으로 뜬다.
EXPOSE 8080 8443
ENV SPRING_PROFILES_ACTIVE=prod
ENV TZ=Asia/Seoul
# 같은 인스턴스에서 다른 서비스가 돌고 있다. 힙 상한을 정해 메모리를 다 가져가지 않게 한다.
ENV JAVA_TOOL_OPTIONS="-Xmx384m"

ENTRYPOINT ["java", "-jar", "app.jar"]
