package service

import (
	"os"
	"strings"
	"testing"
)

func TestUpdateServiceIsBoundToThisPatchRepository(t *testing.T) {
	if githubRepo == "Wei-Shaw/sub2api" || strings.Count(githubRepo, "/") != 1 {
		t.Fatalf("update source is not a patch repository: %q", githubRepo)
	}
	if expected := os.Getenv("SHAREPATCH_REPO"); expected != "" && githubRepo != expected {
		t.Fatalf("update source = %q, want repository %q", githubRepo, expected)
	}
}

func TestCompareVersionsOrdersSharepatchRevisions(t *testing.T) {
	cases := []struct {
		current string
		latest  string
		want    int
	}{
		{current: "0.2.8-share.1", latest: "0.2.8-share.2", want: -1},
		{current: "0.2.8-share.3", latest: "0.2.8-share.2", want: 1},
		{current: "0.2.8", latest: "0.2.8-share.1", want: -1},
		{current: "0.2.8-share.1", latest: "0.2.9-share.1", want: -1},
		{current: "0.2.10-share.1", latest: "0.2.9-share.8", want: 1},
	}
	for _, tc := range cases {
		if got := compareVersions(tc.current, tc.latest); got != tc.want {
			t.Errorf("compareVersions(%q, %q) = %d, want %d", tc.current, tc.latest, got, tc.want)
		}
	}
}
