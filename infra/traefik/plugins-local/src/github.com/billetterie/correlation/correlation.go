// Package correlation ajoute un identifiant de corrélation aux requêtes qui n'en ont pas.
// Un identifiant déjà présent (envoyé par le client ou un autre service) est conservé.
package correlation

import (
	"context"
	"crypto/rand"
	"fmt"
	"net/http"
)

// Config est lue dans la configuration dynamique de Traefik.
type Config struct {
	Header string `json:"header,omitempty"`
}

// CreateConfig renvoie la configuration par défaut.
func CreateConfig() *Config {
	return &Config{Header: "X-Correlation-Id"}
}

type correlation struct {
	next   http.Handler
	header string
}

// New crée le middleware.
func New(_ context.Context, next http.Handler, config *Config, _ string) (http.Handler, error) {
	return &correlation{next: next, header: config.Header}, nil
}

func (c *correlation) ServeHTTP(rw http.ResponseWriter, req *http.Request) {
	identifiant := req.Header.Get(c.header)
	if identifiant == "" {
		identifiant = nouvelUUID()
		req.Header.Set(c.header, identifiant)
	}
	// Renvoyé aussi au client, pour qu'il puisse citer l'identifiant en cas de problème.
	rw.Header().Set(c.header, identifiant)
	c.next.ServeHTTP(rw, req)
}

// nouvelUUID génère un UUID version 4.
func nouvelUUID() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}
