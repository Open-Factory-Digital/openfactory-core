package main

import "net/http"

func main() {
	_ = http.ListenAndServe(":8080", nil)
}
