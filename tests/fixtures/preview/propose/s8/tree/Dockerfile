FROM golang:1.22 AS build
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -o /orders .

FROM gcr.io/distroless/static-debian12
COPY --from=build /orders /orders
EXPOSE 8080
ENTRYPOINT ["/orders"]
