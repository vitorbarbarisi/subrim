#include <stdio.h>
#include "base.h"

int main() {
    printf("Testing base file loading...\n");
    
    BaseData base = load_base_file_for_directory("assets/test");
    
    printf("Loaded base with %d entries, capacity %d\n", base.count, base.capacity);
    
    // Test a few lookups
    for (int time = 1; time <= 5; time++) {
        const BaseEntry *entry = find_entry_by_time(&base, time);
        if (entry) {
            printf("Time %d: '%s'\n", time, entry->zht_text ? entry->zht_text : "NULL");
        } else {
            printf("Time %d: NOT FOUND\n", time);
        }
    }
    
    free_base_data(&base);
    printf("Test completed successfully.\n");
    return 0;
}
