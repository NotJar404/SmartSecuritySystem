using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("person_room_access")]
    public class PersonRoomAccess
    {
        [Key]
        [Column("access_id")]
        public int AccessId { get; set; }

        [Column("person_id")]
        public int PersonId { get; set; }

        [ForeignKey("PersonId")]
        public AuthorizedPersonnel? Person { get; set; }

        [Column("room_id")]
        public int RoomId { get; set; }

        [ForeignKey("RoomId")]
        public Room? Room { get; set; }

        [Column("access_level")]
        [StringLength(20)]
        public string AccessLevel { get; set; } = "allowed";

        [Column("created_at")]
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
