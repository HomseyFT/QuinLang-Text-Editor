// Strings.
//
// A string is a heap object, so it is allocated, moved and reclaimed like
// anything else. Literals are materialised into the heap when the program
// starts; everything built here is an ordinary allocation the collector takes
// back once nothing refers to it.

include "std/string.ql";
include "std/io.ql";

struct Person {
    name: str,
    age: int,
}

fn greet(p: Person): str {
    return "Hi, " + p.name + " (" + int_to_str(p.age) + ")";
}

// Count the words in a string, treating any run of spaces as one separator.
fn word_count(s: str): int {
    let count: int = 0;
    let in_word: bool = false;
    for (let i = 0; i < str_len(s); i = i + 1) {
        if (is_space(str_char_at(s, i))) {
            in_word = false;
        } else {
            if (!in_word) {
                count = count + 1;
            }
            in_word = true;
        }
    }
    return count;
}

fn main(): int {
    println("-- building --");
    let name: str = "Ada";
    println("hello, " + name + "!");
    println(int_to_str(6 * 7));
    println(char_to_str(81) + char_to_str(76));       // QL

    println("-- inspecting --");
    let phrase: str = "the quick brown fox";
    println(str_len(phrase));
    println(str_slice(phrase, 4, 9));                  // quick
    println(str_char_at(phrase, 0));                   // 116, the code for 't'
    println(word_count(phrase));                       // 4

    println("-- escapes --");
    println("a tab:\tdone");
    println("a quote: \"quoted\"");
    println("a backslash: \\");

    println("-- library --");
    println(str_to_upper(phrase));
    println(str_reverse("stressed"));
    println(str_index_of(phrase, "brown"));
    println(str_contains(phrase, "quick"));
    print("[");
    print(str_trim("   padded   "));
    println("]");
    println(str_parse_int("-1234") + 1);
    println(str_repeat("-", 8));

    println("-- strings in structs --");
    let p: Person = Person { name: "Grace" + " Hopper", age: 45 };
    println(greet(p));

    // Build a lot of garbage, then check everything above is still intact:
    // the struct's name field and the literals are traced, and the temporary
    // strings are not.
    for (let i = 0; i < 4000; i = i + 1) {
        let scratch: str = int_to_str(i) + "-" + int_to_str(i * 2);
    }
    gc();

    println("-- after collection --");
    println(greet(p));
    println(phrase);
    println(str_to_upper(name));

    return 0;
}
