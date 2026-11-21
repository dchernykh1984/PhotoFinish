package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PriorityBoardTest {
    private val board = PriorityBoard()

    @Test
    fun `the first lens sends, the others wait while it is connected and behind`() {
        var behind = 5_000L
        var connected = true
        board.register(Lens.MAIN, { connected }, { behind })
        board.register(Lens.TELEPHOTO, { true }, { 60_000 })
        assertTrue(board.allows(Lens.MAIN))
        assertFalse(board.allows(Lens.TELEPHOTO))
        behind = PriorityBoard.BEHIND_MS
        assertTrue(board.allows(Lens.TELEPHOTO))
        behind = 5_000
        connected = false // its laptop gone: it holds nobody back
        assertTrue(board.allows(Lens.TELEPHOTO))
    }

    @Test
    fun `the first lens is the first of the referee's order that sends`() {
        board.order = listOf(Lens.TELEPHOTO, Lens.MAIN)
        board.register(Lens.MAIN, { true }, { 9_000 })
        val off = board.register(Lens.TELEPHOTO, { true }, { 9_000 })
        assertTrue(board.allows(Lens.TELEPHOTO))
        assertFalse(board.allows(Lens.MAIN))
        off()
        assertTrue(board.allows(Lens.MAIN)) // the telephoto sends no more: the main is first
    }

    @Test
    fun `a lens of several senders waits while any of the first's is behind`() {
        board.register(Lens.MAIN, { true }, { 0 })
        board.register(Lens.MAIN, { true }, { 3_000 }) // what it kept before, sent alone
        board.register(Lens.FRONT, { true }, { 0 })
        assertFalse(board.allows(Lens.FRONT))
        assertTrue(PriorityBoard().allows(Lens.FRONT)) // nobody sending: nobody waits
    }
}
