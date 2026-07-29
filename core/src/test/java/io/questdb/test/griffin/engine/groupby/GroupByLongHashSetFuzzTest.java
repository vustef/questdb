/*+*****************************************************************************
 *     ___                  _   ____  ____
 *    / _ \ _   _  ___  ___| |_|  _ \| __ )
 *   | | | | | | |/ _ \/ __| __| | | |  _ \
 *   | |_| | |_| |  __/\__ \ |_| |_| | |_) |
 *    \__\_\\__,_|\___||___/\__|____/|____/
 *
 *  Copyright (c) 2014-2019 Appsicle
 *  Copyright (c) 2019-2026 QuestDB
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *  http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 *
 ******************************************************************************/

package io.questdb.test.griffin.engine.groupby;

import io.questdb.griffin.engine.groupby.FastGroupByAllocator;
import io.questdb.griffin.engine.groupby.GroupByAllocator;
import io.questdb.griffin.engine.groupby.GroupByLongHashSet;
import io.questdb.std.MemoryTracker;
import io.questdb.std.Numbers;
import io.questdb.std.Rnd;
import io.questdb.test.AbstractCairoTest;
import io.questdb.test.tools.TestUtils;
import org.junit.Assert;
import org.junit.Test;

import java.util.Set;

public class GroupByLongHashSetFuzzTest extends AbstractCairoTest {

    @Test
    public void testFuzzWithLongNullAsNoKeyValue() throws Exception {
        testFuzz(Numbers.LONG_NULL);
    }

    @Test
    public void testFuzzWithZeroAsNoKeyValue() throws Exception {
        testFuzz(0);
    }

    @Test
    public void testMerge() throws Exception {
        assertMemoryLeak(() -> {
            try (CountingGroupByAllocator allocator = new CountingGroupByAllocator()) {
                GroupByLongHashSet setA = new GroupByLongHashSet(16, 0.5, -1);
                setA.setAllocator(allocator);
                setA.of(0);
                GroupByLongHashSet setB = new GroupByLongHashSet(16, 0.9, -1);
                setB.setAllocator(allocator);
                setB.of(0);

                final int destSize = 10;
                final int srcSize = 1000;

                for (int i = 0; i < destSize; i++) {
                    setA.add(i);
                }
                Assert.assertEquals(destSize, setA.size());
                Assert.assertTrue(setA.capacity() >= destSize);

                for (int i = destSize; i < destSize + srcSize; i++) {
                    setB.add(i);
                }
                Assert.assertEquals(srcSize, setB.size());
                Assert.assertTrue(setB.capacity() >= srcSize);

                allocator.resetMallocCount();
                setA.merge(setB);
                Assert.assertEquals(1, allocator.getMallocCount());
                Assert.assertEquals(destSize + srcSize, setA.size());
                for (int i = 0; i < destSize + srcSize; i++) {
                    Assert.assertTrue(setA.keyIndex(i) < 0);
                }

                allocator.resetMallocCount();
                setA.merge(setA);
                Assert.assertEquals(0, allocator.getMallocCount());
                Assert.assertEquals(destSize + srcSize, setA.size());
            }
        });
    }

    private void testFuzz(long noKeyValue) throws Exception {
        assertMemoryLeak(() -> {
            final int N = 1000;
            final Rnd rnd = TestUtils.generateRandom(LOG);
            final long seed0 = rnd.getSeed0();
            final long seed1 = rnd.getSeed1();
            try (GroupByAllocator allocator = new FastGroupByAllocator(64, Numbers.SIZE_1GB)) {
                GroupByLongHashSet set = new GroupByLongHashSet(16, 0.7, noKeyValue);
                set.setAllocator(allocator);
                set.of(0);

                Set<Long> referenceSet = new java.util.HashSet<>();
                for (int i = 0; i < N; i++) {
                    long val = rnd.nextPositiveLong() + 1;
                    set.add(val);
                    referenceSet.add(val);
                }

                Assert.assertEquals(referenceSet.size(), set.size());
                Assert.assertTrue(set.capacity() >= referenceSet.size());

                rnd.reset(seed0, seed1);

                for (int i = 0; i < N; i++) {
                    Assert.assertTrue(set.keyIndex(rnd.nextPositiveLong() + 1) < 0);
                }

                set.of(0);
                rnd.reset(seed0, seed1);

                referenceSet.clear();
                for (int i = 0; i < N; i++) {
                    long val = rnd.nextPositiveLong() + 1;
                    long index = set.keyIndex(val);
                    Assert.assertTrue(index >= 0 || referenceSet.contains(val));
                    set.addAt(index, val);
                    referenceSet.add(val);
                }
            }
        });
    }

    private static class CountingGroupByAllocator implements GroupByAllocator {
        private final GroupByAllocator delegate = new FastGroupByAllocator(64, Numbers.SIZE_1GB);
        private int mallocCount;

        @Override
        public long allocated() {
            return delegate.allocated();
        }

        @Override
        public void clear() {
            delegate.clear();
        }

        @Override
        public void close() {
            delegate.close();
        }

        @Override
        public void free(long ptr, long size) {
            delegate.free(ptr, size);
        }

        public int getMallocCount() {
            return mallocCount;
        }

        @Override
        public long malloc(long size) {
            mallocCount++;
            return delegate.malloc(size);
        }

        @Override
        public long realloc(long ptr, long oldSize, long newSize) {
            return delegate.realloc(ptr, oldSize, newSize);
        }

        @Override
        public void reopen() {
            delegate.reopen();
        }

        public void resetMallocCount() {
            mallocCount = 0;
        }

        @Override
        public void setMemoryTracker(MemoryTracker tracker) {
            delegate.setMemoryTracker(tracker);
        }
    }
}
